import os
import sys
import json
import time
import re
import shutil
import subprocess
import threading
import uuid
import requests
import ast
from typing import Dict, Any, Generator, List, Optional, Callable
# Import relativo: el absoluto solo funcionaba con backend/ en sys.path y rompía
# al importar el paquete como backend.ai_engine (p. ej. desde los tests).
from .web_search_engine import WebSearchEngine
from . import motor_moe

_PENSAMIENTO_RE = re.compile(r"<think(?:ing)?>.*?</think(?:ing)?>\s*", re.S | re.I)

OLLAMA_BASE_URL = "http://localhost:11434"

# Motor de Ollama: desde las versiones con llama-server, el ejecutable «ollama» no
# carga modelos por sí solo; los carga el binario llama-server que viene al lado, en
# <bin>/../lib/ollama (junto con las bibliotecas de CUDA). Un Ollama copiado sin esa
# carpeta arranca y responde, pero falla al cargar cualquier modelo y no ve la GPU.
RUNTIME_COMPLETO, RUNTIME_DESCONOCIDO, RUNTIME_INCOMPLETO = 2, 1, 0
MENSAJE_RUNTIME_INCOMPLETO = (
    "El Ollama que está en marcha está incompleto: le falta su motor llama-server "
    "(y sin él tampoco usa la GPU), así que no puede cargar ningún modelo. "
    "Reinicia Ollama desde Prig (Modelos → Servidor → Guardar y reiniciar Ollama) "
    "para que use uno completo."
)



# ---------------------------------------------------------------------------
# Cancelación por petición
#
# Cada petición HTTP que genera con el modelo (app._ndjson_en_hilo) corre en su hilo y deja
# aquí SU evento de cancelación. Si el cliente se va (cierra la sección, recarga, pulsa
# Cancelar), se activa solo ese evento: se detiene esa generación y no las de las demás
# secciones. Sin esto el modelo seguía generando en la GPU para nadie hasta terminar.
# ---------------------------------------------------------------------------
_contexto_hilo = threading.local()


def cancelacion_actual() -> "Optional[threading.Event]":
    """ El evento de cancelación de la petición que atiende este hilo, o None """
    return getattr(_contexto_hilo, "cancelar", None)


def fijar_cancelacion(evento: "Optional[threading.Event]"):
    _contexto_hilo.cancelar = evento

def _dirs_libreria_ollama(binario: str) -> List[str]:
    """ Dónde busca Ollama su carpeta lib/ollama, en el mismo orden que él """
    exe = os.path.dirname(os.path.realpath(binario))
    return [os.path.join(exe, "..", "lib", "ollama"), os.path.join(exe, "build", "lib", "ollama"),
            os.path.join(exe, "dist", "linux-amd64", "lib", "ollama"), os.path.join(exe, "dist", "linux_amd64", "lib", "ollama")]


def estado_runtime_ollama(binario: str) -> int:
    """ ¿Tiene este Ollama su motor al lado?

    COMPLETO: hay un llama-server ejecutable. INCOMPLETO: existe lib/ollama pero sin
    llama-server (instalación a medias, como un install.sh interrumpido). DESCONOCIDO:
    no hay lib/ollama; puede ser una versión antigua que lo llevaba dentro. """
    dirs = _dirs_libreria_ollama(binario)
    for d in dirs:
        motor = os.path.join(d, "llama-server")
        if os.path.isfile(motor) and os.access(motor, os.X_OK):
            return RUNTIME_COMPLETO
    if any(os.path.isdir(d) for d in dirs):
        return RUNTIME_INCOMPLETO
    return RUNTIME_DESCONOCIDO


def explicar_error_motor(texto: str) -> Optional[str]:
    """ Mensaje accionable para los errores de Ollama que no dependen del modelo """
    if "llama-server binary not found" in (texto or ""):
        return MENSAJE_RUNTIME_INCOMPLETO
    return None

# El chat con herramientas (consultas repetidas, última ronda, cortes por bucle) está en Rust: prig_ia::generar

CONFIG_PATH = os.path.expanduser("~/.prig_ai_config.json")

# Las herramientas de los chats en curso: el servidor de Rust genera y pide ejecutar cada una (/api/interno/herramienta)
SESIONES_HERRAMIENTAS: Dict[str, Any] = {}


def reparar_y_parsear_json(response_text: str) -> dict:
    """ Extrae y repara de forma robusta cualquier salida JSON de un modelo de IA.
    Tolera bloques markdown, comas sobrantes, saltos de línea sin escapar dentro de cadenas
    (código), comentarios, comillas internas sin escapar y cierres incompletos. """
    if not (response_text or "").strip():
        raise ValueError("Respuesta vacía del modelo de IA")

    clean = _PENSAMIENTO_RE.sub("", response_text).strip()

    candidatos = []
    for m in re.finditer(r"```(?:json)?\s*([\{\[].*?[\}\]])\s*```", clean, re.S):
        candidatos.append(m.group(1).strip())

    start = clean.find("{")
    end = clean.rfind("}")
    if start != -1 and end != -1 and end > start:
        cand_ext = clean[start:end+1].strip()
        if cand_ext not in candidatos:
            candidatos.append(cand_ext)

    if clean not in candidatos:
        candidatos.append(clean)

    def _intentar_parsear(s: str) -> Optional[dict]:
        def _como_dict(val):
            if isinstance(val, dict):
                return val
            if isinstance(val, list) and val and isinstance(val[0], dict):
                return val[0]
            return None

        try:
            res = json.loads(s)
            d = _como_dict(res)
            if d is not None:
                return d
        except Exception:
            pass
        try:
            res = json.loads(s, strict=False)
            d = _como_dict(res)
            if d is not None:
                return d
        except Exception:
            pass
        sin_comas = re.sub(r",\s*([\]}])", r"\1", s)
        try:
            res = json.loads(sin_comas, strict=False)
            d = _como_dict(res)
            if d is not None:
                return d
        except Exception:
            pass
        try:
            s_doble = re.sub(r"'([^'\\]*(?:\\.[^'\\]*)*)'", r'"\1"', sin_comas)
            s_doble = re.sub(r"\bTrue\b", "true", s_doble)
            s_doble = re.sub(r"\bFalse\b", "false", s_doble)
            s_doble = re.sub(r"\bNone\b", "null", s_doble)
            res = json.loads(s_doble, strict=False)
            d = _como_dict(res)
            if d is not None:
                return d
        except Exception:
            pass
        try:
            s_py = re.sub(r"\btrue\b", "True", sin_comas)
            s_py = re.sub(r"\bfalse\b", "False", s_py)
            s_py = re.sub(r"\bnull\b", "None", s_py)
            res = ast.literal_eval(s_py)
            d = _como_dict(res)
            if d is not None:
                return d
        except Exception:
            pass
        return None

    def _escapar_comillas_internas(texto: str) -> str:
        i = 0
        n = len(texto)
        while i < n:
            if texto[i] == '"':
                j = i + 1
                while j < n:
                    if texto[j] == "\\":
                        j += 2
                        continue
                    if texto[j] == '"':
                        k = j + 1
                        while k < n and texto[k] in " \t\r\n":
                            k += 1
                        if k < n and texto[k] in ",:}]":
                            break
                        else:
                            texto = texto[:j] + '\\"' + texto[j+1:]
                            n += 1
                            j += 2
                            continue
                    j += 1
                i = j + 1
            else:
                i += 1
        return texto

    def _cerrar_incompleto(texto: str) -> str:
        pila = []
        en_str = False
        esc = False
        for ch in texto:
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == '"':
                en_str = not en_str
                continue
            if not en_str:
                if ch in "{[":
                    pila.append("}" if ch == "{" else "]")
                elif ch in "}]":
                    if pila and pila[-1] == ch:
                        pila.pop()
        agregado = '"' if en_str else ""
        while pila:
            agregado += pila.pop()
        return texto + agregado

    for cand in candidatos:
        res = _intentar_parsear(cand)
        if res is not None:
            return res

        try:
            res = _intentar_parsear(_escapar_comillas_internas(cand))
            if res is not None:
                return res
        except Exception:
            pass

        try:
            res = _intentar_parsear(_cerrar_incompleto(cand))
            if res is not None:
                return res
        except Exception:
            pass

        try:
            res = _intentar_parsear(_cerrar_incompleto(_escapar_comillas_internas(cand)))
            if res is not None:
                return res
        except Exception:
            pass

    # Heurística de rescate para desafíos si falló el parser estricto
    m_tit = re.search(r'"titulo"\s*:\s*"([^"]+)"', clean)
    if m_tit:
        titulo = m_tit.group(1).strip()
        m_enun = re.search(r'"enunciado"\s*:\s*"(.*?)(?="\s*,\s*"(?:nivel|conceptos|paginas))', clean, re.S)
        enunciado = m_enun.group(1).strip() if m_enun else "Resuelve el desafío propuesto."
        m_niv = re.search(r'"nivel"\s*:\s*"([^"]+)"', clean)
        nivel = m_niv.group(1).strip() if m_niv else "intermedio"

        paginas_list = []
        for mp in re.finditer(r'\{\s*"nombre"\s*:\s*"([^"]+)".*?"contenido"\s*:\s*"(.*?)(?="\s*\}\s*[,\]])', clean, re.S):
            paginas_list.append({"nombre": mp.group(1), "contenido": mp.group(2).replace('\\n', '\n')})

        if paginas_list:
            return {
                "titulo": titulo,
                "enunciado": enunciado,
                "nivel": nivel,
                "conceptos": ["algoritmos"],
                "paginas": paginas_list,
                "referencia": paginas_list,
                "pruebas": ["assert True"]
            }

    err_msg = f"No se pudo extraer un JSON válido de la respuesta del modelo: {clean[:160]}..."
    print(f"⚠️ {err_msg}")
    raise ValueError(err_msg)


class AIEngine:
    def __init__(self, base_url: str = OLLAMA_BASE_URL):
        self.base_url = base_url
        self.web_search = WebSearchEngine()
        self.config_path = CONFIG_PATH
        self._active_streams = set()
        self._streams_lock = threading.Lock()
        self._cancelables = set()      # chats en curso que «Detener» debe despertar
        self._usados: set = set()      # modelos que Prig cargó: se sueltan al cerrar
        self._ollama_proc: Optional[subprocess.Popen] = None
        self.config = {
            "ollama_url": base_url,
            "agent1_model": "qwen2.5-coder:7b",
            "agent2_model": "qwen2.5-coder:7b",
            "agent3_model": "qwen2.5-coder:7b",
            "designer_model": "qwen2.5-coder:7b",
            # Un modelo por tarea (Configuración global). Vacío = automático: lo que
            # elija cada sección, como antes. Ollama los carga solo al usarlos.
            "modelo_codigo": "",         # escribir código: Prig//:, crear desafíos
            "modelo_explicar": "",       # explicar: Kaggle, GitHub, explicaciones del editor
            "modelo_autocompletar": "",  # rellenar código mientras se escribe
            "depth_level": "intermediate",
            "temperature": 0.3,
            "num_ctx": 4096,
            "num_gpu": -1,
            "num_thread": 0,
            "num_predict": 2048,
            "low_vram": False,
            "f16_kv": True,
            # True: temperatura, top_k, top_p y repeat_penalty los decide cada modelo
            # (su Modelfile) y las capas de Prig; los valores globales no se envían.
            "muestreo_del_modelo": True,
            "keep_alive": "5m",
            "top_k": 40,
            "top_p": 0.9,
            "repeat_penalty": 1.1,
            "exec_timeout": 25,
            # Motor MoE (Qwen3.6-35B-A3B con expertos calientes en la GPU, ai_engine/motor_moe.py)
            "moe_contexto": motor_moe.CONTEXTO,
            "moe_hilos": 0,              # 0 = uno por núcleo P (hasta 4)
            "moe_calientes": "auto",     # expertos por capa en la GPU; auto = los que quepan
            "moe_modo": motor_moe.MODO,  # exacto | equilibrado | rapido (omite expertos fríos de poco peso)
            "moe_mtp": True,             # decodificación especulativa con la cabeza MTP del modelo
            "moe_nucleo": motor_moe.NUCLEO,  # q8: núcleo en Q8 (más calidad) · q4: el de Ollama (más rápido)
            # Caché de estados del motor en disco (docs/plan-texto-primero.md): tope en GB (0 = no se guarda ninguno) y
            # disco libre que el caché nunca toca. 32 = el tope fijo que había: el valor final se decide al medir
            "moe_cache_gb": 32,
            "moe_cache_reserva_gb": 20,
            # Banco del proyecto: tokens de contexto por pregunta y del mapa; modelo del análisis ("" = automático)
            "banco_presupuesto": 6000,
            "banco_mapa": 3000,
            "banco_modelo": "",
            # Cómo responde el chat con el banco: auto (lectura guardada de la unidad si la hay) | general (siempre desde
            # el texto del banco) | unidad (leerla si hace falta). docs/plan-texto-primero.md
            "banco_modo": "auto",
        }
        self._load_config()
        self._firma_vista = self._firma_config()

    def _load_config(self) -> None:
        """ La configuración se guardaba solo en memoria y se perdía al reiniciar """
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                # 16K era el contexto por defecto del motor MoE antes de que existieran los modos y el
                # contexto automático: una configuración de entonces pasa al automático
                if saved.get("moe_contexto") == 16384 and "moe_modo" not in saved:
                    saved.pop("moe_contexto")
                for k, v in saved.items():
                    if k in self.config and v is not None:
                        self.config[k] = v
                if saved.get("ollama_url"):
                    self.base_url = saved["ollama_url"]
        except Exception as e:
            print(f"⚠️ No se pudo leer la configuración de IA guardada: {e}")

    def _firma_config(self):
        try:
            st = os.stat(self.config_path)
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def _refrescar_config(self) -> None:
        """ El servidor de Rust también escribe este archivo (los ajustes del motor MoE): si cambió en disco, se relee
        antes de usarlo o de guardar encima (si no, guardar otro ajuste desharía el suyo) """
        firma = self._firma_config()
        if firma is not None and firma != getattr(self, "_firma_vista", None):
            self._load_config()
            self._firma_vista = firma

    def _save_config(self) -> None:
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            self._firma_vista = self._firma_config()
        except Exception as e:
            print(f"⚠️ No se pudo guardar la configuración de IA: {e}")

    def get_config(self) -> Dict[str, Any]:
        self._refrescar_config()
        return self.config

    ROLES = {
        "codigo": "modelo_codigo",
        "explicar": "modelo_explicar",
        "tutor": "modelo_explicar",
        "autocompletar": "modelo_autocompletar"
    }

    def modelo_para(self, rol: Optional[str], pedido: Optional[str] = None) -> Optional[str]:
        """ El modelo de una tarea: el que se pide explícitamente, si no el elegido para
        ese rol en la configuración global, si no None (automático) """
        pedido = (pedido or "").strip()
        if pedido:
            return pedido
        clave = self.ROLES.get(rol or "", rol or "")
        return (str(self.config.get(clave) or "")).strip() or None

    def update_config(self, new_cfg: Dict[str, Any]) -> Dict[str, Any]:
        self._refrescar_config()
        for k, v in new_cfg.items():
            if k in self.config and v is not None:
                self.config[k] = v
        if new_cfg.get("ollama_url"):
            self.base_url = new_cfg["ollama_url"]
        self._save_config()
        return self.config

    def _parse_version(self, v_str: Optional[str]) -> List[int]:
        if not v_str:
            return [0, 0, 0]
        nums = [int(x) for x in re.findall(r"\d+", v_str)][:3]
        return nums + [0] * (3 - len(nums))

    def _version_ge(self, v1: str, v2: str) -> bool:
        return self._parse_version(v1) >= self._parse_version(v2)

    @staticmethod
    def _candidatos_ollama() -> List[str]:
        """ Rutas donde puede estar Ollama, de más a menos preferida (el de Prig primero) """
        home = os.path.expanduser("~")
        prig_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return [
            os.path.join(prig_root, "bin", "ollama"),
            os.path.join(prig_root, "bin", "bin", "ollama"),
            os.path.join(home, ".local", "bin", "ollama"),
            "/usr/local/bin/ollama",
            "/usr/bin/ollama",
            shutil.which("ollama") or ""
        ]

    def get_best_ollama_binary(self) -> Optional[tuple]:
        """
        Escanea todas las rutas candidatas donde puede residir el ejecutable de Ollama,
        comprueba su versión real (--version) y devuelve la tupla (ruta_binario, version).

        Manda, por este orden: que esté completo (con su llama-server al lado), la
        versión, y el orden de la lista (el de Prig primero). Antes, a igual versión
        ganaba el último de la lista: con un /usr/local/bin/ollama copiado sin su
        carpeta lib/ollama, Prig arrancaba ese y ningún modelo cargaba.
        """
        candidates = self._candidatos_ollama()

        seen_paths = set()
        mejor = None                    # (clave de orden, ruta, versión)
        for indice, cand in enumerate(candidates):
            if not cand:
                continue
            real = os.path.realpath(cand)
            if real in seen_paths:
                continue
            seen_paths.add(real)
            if not (os.path.isfile(cand) and os.access(cand, os.X_OK)):
                continue
            ver = None
            try:
                proc = subprocess.run([cand, "--version"], capture_output=True, text=True, timeout=3)
                m = re.search(r"(\d+\.\d+[\.\d]*)", (proc.stdout or "") + (proc.stderr or ""))
                ver = m.group(1) if m else None
            except Exception:
                pass
            clave = (estado_runtime_ollama(cand), self._parse_version(ver or "0.0.0"), -indice)
            if mejor is None or clave > mejor[0]:
                mejor = (clave, cand, ver or "0.0.0")

        if mejor:
            return mejor[1], mejor[2]
        return None

    @staticmethod
    def binario_ollama_en_marcha() -> Optional[str]:
        """ Ejecutable del «ollama serve» que está corriendo, si se puede ver """
        try:
            import psutil
            for proc in psutil.process_iter(['name', 'cmdline']):
                try:
                    cmd = proc.info.get('cmdline') or []
                    if len(cmd) >= 2 and os.path.basename(cmd[0]) == 'ollama' and 'serve' in cmd[1:]:
                        return proc.exe()
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
        except Exception:
            pass
        return None

    def kill_ollama_processes(self):
        """ Detiene cualquier proceso ollama serve activo para permitir reinicio limpio en el puerto 11434 """
        try:
            import psutil
            current_pid = os.getpid()
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if proc.pid == current_pid:
                        continue
                    name = (proc.info.get('name') or '').lower()
                    cmd = " ".join(proc.info.get('cmdline') or []).lower()
                    if 'ollama' in name or 'ollama serve' in cmd:
                        proc.terminate()
                        try:
                            proc.wait(timeout=2.0)
                        except (psutil.TimeoutExpired, psutil.NoSuchProcess):
                            proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
        except Exception as e:
            print(f"Error deteniendo procesos previos de Ollama: {e}")

        if self._ollama_proc is not None:
            try:
                self._ollama_proc.terminate()
                self._ollama_proc.wait(timeout=2.0)
            except Exception:
                try:
                    self._ollama_proc.kill()
                except Exception:
                    pass
            self._ollama_proc = None
        time.sleep(1.0)

    def try_autostart_ollama(self, force_restart: bool = False) -> bool:
        """ Arranca (o reinicia) Ollama si no responde, está incompleto o hay uno más nuevo. Lo hace el servidor de
        Rust, dueño del `ollama serve` que lanza Prig (muere con Prig: PDEATHSIG); ver prig_ia::ollama """
        if os.environ.get("PRIG_SIN_AUTOARRANQUE_OLLAMA") == "1":
            return False
        puerto = os.environ.get("PRIG_PUERTO_RUST")
        if not puerto:
            return False
        try:
            r = requests.post(f"http://127.0.0.1:{puerto}/api/ollama/asegurar", json={"forzar": bool(force_restart)}, timeout=60)
            return bool(r.json().get("ok"))
        except Exception:
            return False

    def check_health(self) -> Dict[str, Any]:
        self.try_autostart_ollama()
        try:
            res = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if res.status_code == 200:
                models = [m["name"] for m in res.json().get("models", [])]
                models += [m["name"] for m in self._modelos_propios()]
                ver = "?"
                try:
                    vres = requests.get(f"{self.base_url}/api/version", timeout=2)
                    if vres.status_code == 200:
                        ver = vres.json().get("version", "?")
                except Exception:
                    pass
                return {"status": "ok", "online": True, "version": ver, "models": models, "url": self.base_url}
            return {"status": "error", "online": False, "message": f"Ollama HTTP {res.status_code}", "models": []}
        except Exception as e:
            return {"status": "offline", "online": False, "message": str(e), "models": []}

    def check_ollama_status(self) -> Dict[str, Any]:
        return self.check_health()

    def reload_ollama(self) -> Dict[str, Any]:
        self.try_autostart_ollama(force_restart=True)
        return self.check_health()

    def get_detailed_models(self) -> Dict[str, Any]:
        self.try_autostart_ollama()
        ver = "?"
        try:
            vres = requests.get(f"{self.base_url}/api/version", timeout=2)
            if vres.status_code == 200:
                ver = vres.json().get("version", "?")
        except Exception:
            pass
        try:
            res = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if res.status_code == 200:
                raw_models = res.json().get("models", [])
                detailed = []
                for m in raw_models:
                    details = m.get("details", {})
                    size_gb = round(m.get("size", 0) / (1024**3), 2)
                    detailed.append({
                        "name": m.get("name"),
                        "size_gb": size_gb,
                        "quantization": details.get("quantization_level", "N/A"),
                        "family": details.get("family", "N/A"),
                        "parameter_size": details.get("parameter_size", "N/A"),
                        "format": details.get("format", "gguf"),
                        "modified_at": m.get("modified_at", "")[:10],
                        "available": True
                    })
                return {"online": True, "models": detailed + self._modelos_propios(), "version": ver, "url": self.base_url}
            return {"online": False, "models": self._modelos_propios(), "version": ver, "message": f"HTTP {res.status_code}"}
        except Exception as e:
            return {"online": False, "models": self._modelos_propios(), "version": ver, "message": str(e)}

    @staticmethod
    def _modelos_propios() -> List[Dict[str, Any]]:
        """ Modelos que sirve Prig sin Ollama: el motor MoE, si está compilado y el modelo descargado """
        disp = motor_moe.Motor.disponible()
        if not disp["disponible"]:
            return []
        try:
            tam = os.path.getsize(disp["modelo"])
            fecha = time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(motor_moe.SERVIDOR)))
        except OSError:
            tam, fecha = 0, ""
        return [{"name": motor_moe.NOMBRE, "size_gb": round(tam / (1024 ** 3), 2), "quantization": "Q4_K_S",
                 "family": "qwen35moe", "parameter_size": "35B-A3B", "format": "gguf", "modified_at": fecha,
                 "available": True, "motor": "moe"}]

    def delete_model(self, model_name: str) -> bool:
        try:
            res = requests.delete(f"{self.base_url}/api/delete", json={"name": model_name}, timeout=10)
            return res.status_code == 200
        except Exception as e:
            print(f"Error eliminando modelo {model_name}: {e}")
            return False

    def pull_model(self, model_name: str) -> Generator[str, None, None]:
        self.try_autostart_ollama()
        raw_name = (model_name or "").strip()
        # Sanitizar si el cliente envía descripciones accidentales (ej: "tag (descripción)")
        clean_name = re.split(r"[\s(]", raw_name)[0].strip().lower() if raw_name else ""

        # Mapeo de alias para modelos con tags comunitarios hacia el tag oficial en Ollama
        alias_map = {
            "qwen3-30b-a3b:r1-distill": "qwen3:30b-a3b",
            "qwen3-30b-a3b": "qwen3:30b-a3b",
            "qwen3.6-35b-a3b": "qwen3.6:35b-a3b",
            "deepseek-coder-v2-lite": "deepseek-coder-v2:16b",
            "deepseek-coder-v2:lite": "deepseek-coder-v2:16b",
        }
        target_name = alias_map.get(clean_name, clean_name)

        url = f"{self.base_url}/api/pull"
        payload = {"name": target_name, "stream": True}
        try:
            res = requests.post(url, json=payload, stream=True, timeout=600)
            if res.status_code != 200:
                err_text = res.text
                err_lower = err_text.lower()
                if res.status_code == 412 or "newer version" in err_lower:
                    yield f"Error desde Ollama: El modelo '{target_name}' requiere una versión más reciente de Ollama. Actualiza desde Configuración o ejecuta 'run.sh'.\n"
                elif "file does not exist" in err_lower or "not found" in err_lower or res.status_code == 404:
                    yield f"Error desde Ollama: El modelo '{target_name}' no existe en el registro central de Ollama.\n"
                else:
                    yield f"Error desde Ollama (HTTP {res.status_code}): {err_text}\n"
                return

            for line in res.iter_lines():
                if line:
                    try:
                        data = json.loads(line.decode('utf-8'))
                        if "error" in data:
                            err_msg = str(data['error'])
                            err_lower = err_msg.lower()
                            if "newer version" in err_lower:
                                yield f"Error en descarga: Ollama necesita actualizarse para '{target_name}'. Actualiza desde Configuración o ejecuta 'run.sh'.\n"
                            elif "file does not exist" in err_lower or "not found" in err_lower:
                                yield (f"Error en descarga: El modelo '{target_name}' no se encuentra en el registro oficial de Ollama. "
                                       f"Si es un modelo GGUF comunitario de Hugging Face, impórtalo con: 'ollama create {clean_name} -f Modelfile'.\n")
                            elif "directorio" in err_lower or "directory" in err_lower or "invalid" in err_lower:
                                yield f"Error en descarga: Tag de modelo inválido ('{raw_name}'). Usa solo letras, números y dos puntos (ej: qwen3:30b-a3b).\n"
                            else:
                                yield f"Error en descarga: {err_msg}\n"
                            return

                        status = data.get("status", "")
                        completed = data.get("completed", None)
                        total = data.get("total", None)

                        if completed is not None and total is not None and total > 0:
                            pct = int((completed / total) * 100)
                            size_mb = round(completed / (1024 * 1024), 1)
                            total_mb = round(total / (1024 * 1024), 1)
                            yield f"{status} ({pct}%) - {size_mb}MB / {total_mb}MB\n"
                        elif status:
                            yield f"{status}\n"
                    except Exception:
                        yield f"{line.decode('utf-8')}\n"
        except requests.exceptions.RequestException as e:
            yield f"Error de conexión de red con Ollama ({self.base_url}): {str(e)}\n"
        except Exception as e:
            yield f"Error inesperado al descargar modelo: {str(e)}\n"


    # FlowEngine y otros consultan esto antes de pasar `uso` (los motores falsos
    # de las pruebas no lo aceptan)
    admite_uso = True

    def _build_options(self, overrides: Optional[Dict[str, Any]] = None,
                       model: Optional[str] = None, uso: Optional[str] = None) -> Dict[str, Any]:
        """ Opciones que se mandan a Ollama, de menos a más prioridad:

          1. configuración global de IA (contexto, tope de respuesta, hilos)
          2. capas de Prig: todos los modelos → este modelo → este uso → modelo en uso
          3. lo que exige la llamada (un paso JSON, la calibración…)

        Lo que ninguna fija no se envía y Ollama usa lo del modelo. Antes se mandaban
        siempre temperatura 0.3, top_k 40, top_p 0.9 y repeat_penalty 1.1, pisando lo
        que cada modelo trae de fábrica. low_vram y f16_kv tampoco se envían:
        medido, Ollama los acepta pero no llegan al motor.
        """
        options: Dict[str, Any] = {}
        if not self.config.get("muestreo_del_modelo", True):
            for clave, tipo in (("temperature", float), ("top_k", int), ("top_p", float), ("repeat_penalty", float)):
                if self.config.get(clave) is not None:
                    options[clave] = tipo(self.config[clave])
        try:
            options["num_ctx"] = int(self.config.get("num_ctx", 4096))
        except (TypeError, ValueError):
            pass
        num_gpu = int(self.config.get("num_gpu", -1) or -1)
        if num_gpu >= 0:
            options["num_gpu"] = num_gpu
        num_thread = int(self.config.get("num_thread", 0) or 0)
        if num_thread > 0:
            options["num_thread"] = num_thread
        elif getattr(self, "gobernador", None) is not None:
            # Modo frío: con el modelo en RAM, 4 hilos en los núcleos E rinden como 8 en todos y
            # calientan menos (recursos/frio.py). Solo si el usuario no fijó los hilos.
            try:
                from recursos import frio
                from recursos.almacen import almacen
                if {**frio.POR_DEFECTO, **almacen().frio()}["activo"]:
                    hilos = frio.hilos_en_frio()
                    if hilos:
                        options["num_thread"] = hilos
            except Exception:
                pass
        num_predict = int(self.config.get("num_predict", 0) or 0)
        if num_predict > 0:
            options["num_predict"] = num_predict

        try:
            from ollama_opciones import config as config_modelos, limpiar_para_ollama
            options.update(config_modelos().resolver(model, uso)["opciones"])
        except Exception as e:
            print(f"⚠️ No se pudo leer la configuración por modelo: {e}")
            limpiar_para_ollama = lambda o: o  # noqa: E731

        if overrides:
            options.update({k: v for k, v in overrides.items() if v is not None})
        if motor_moe.es_moe(model):
            # El contexto del motor MoE se fija al arrancarlo (Temperaturas → Motor MoE): las
            # métricas («contexto usado») se calculan con ese
            options["num_ctx"] = self.motor_moe().contexto_deseado()
        return limpiar_para_ollama(options)

    def _campos_peticion(self, model: Optional[str], uso: Optional[str]) -> Dict[str, Any]:
        """ keep_alive, think, instrucciones extra, truncate y shift de las capas """
        try:
            from ollama_opciones import config as config_modelos
            return config_modelos().resolver(model, uso)["campos"]
        except Exception:
            return {}

    _caps_cache: Dict[str, Any] = {}

    def capacidades(self, model: str) -> List[str]:
        """ completion, tools, thinking, insert, vision, embedding (con caché de 10 min).
        Mandar `think` a un modelo que no piensa da error 400 (medido). """
        if motor_moe.es_moe(model):
            return list(motor_moe.CAPACIDADES)
        ahora = time.time()
        guardado = self._caps_cache.get(model)
        if guardado and ahora - guardado[0] < 600:
            return guardado[1]
        try:
            r = requests.post(f"{self.base_url}/api/show", json={"model": model}, timeout=10)
            caps = r.json().get("capabilities") or [] if r.status_code == 200 else []
        except Exception:
            caps = []
        self._caps_cache[model] = (ahora, caps)
        return caps

    def _completar_payload(self, payload: Dict[str, Any], model: str, uso: Optional[str],
                           think: Optional[bool], system_prompt: str) -> Dict[str, Any]:
        """ Campos de la petición a partir de las capas y de lo que pide la llamada """
        campos = self._campos_peticion(model, uso)
        keep_alive = campos.get("keep_alive", self.config.get("keep_alive"))
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive
        if think is None:
            think = campos.get("think")
        if think is not None and "thinking" in self.capacidades(model):
            payload["think"] = bool(think)
        extra = (campos.get("system_extra") or "").strip()
        sistema = "\n\n".join(t for t in (system_prompt, extra) if t)
        for clave in ("truncate", "shift"):
            if clave in campos:
                payload[clave] = campos[clave]
        return {"sistema": sistema}

    @staticmethod
    def metricas(datos: Dict[str, Any], num_ctx: Optional[int] = None) -> Dict[str, Any]:
        """ Lo que Ollama devuelve al terminar, en unidades legibles """
        def seg(ns):
            return round((ns or 0) / 1e9, 3)
        num_ctx = datos.get("contexto") or num_ctx      # motor MoE: su contexto real
        eval_s = seg(datos.get("eval_duration"))
        prompt_s = seg(datos.get("prompt_eval_duration"))
        m = {
            "total_s": seg(datos.get("total_duration")),
            "carga_s": seg(datos.get("load_duration")),
            "tokens_prompt": datos.get("prompt_eval_count", 0),
            "tokens_respuesta": datos.get("eval_count", 0),
            "lectura_tok_s": round(datos.get("prompt_eval_count", 0) / prompt_s, 1) if prompt_s else None,
            "generacion_tok_s": round(datos.get("eval_count", 0) / eval_s, 1) if eval_s else None,
            "motivo_fin": datos.get("done_reason"),
            "proyecto": datos.get("proyecto"),     # motor MoE: proyecto leído o restaurado de disco
            "cortada": datos.get("done_reason") == "length",
        }
        if num_ctx:
            usados = (m["tokens_prompt"] or 0) + (m["tokens_respuesta"] or 0)
            m["contexto"] = num_ctx
            m["contexto_usado_pct"] = round(100 * usados / num_ctx, 1)
        return m

    @staticmethod
    def _error_de(res) -> str:
        try:
            return (res.json().get("error") or "")[:300]
        except Exception:
            return (getattr(res, "text", "") or "")[:300]

    def motor_moe(self) -> "motor_moe.Motor":
        """ El motor MoE, con la VRAM que le dejan los modelos de Ollama y los ajustes de IA """
        return motor_moe.motor(
            liberar_gpu=self._descargar_ollama,
            propios=self._modelos_de_prig_en_ollama,
            ajustes=lambda: {"contexto": self.config.get("moe_contexto"), "hilos": self.config.get("moe_hilos"),
                             "calientes": self.config.get("moe_calientes"), "modo": self.config.get("moe_modo"),
                             "mtp": self.config.get("moe_mtp", True), "nucleo": self.config.get("moe_nucleo"),
                             "cache_gb": self.config.get("moe_cache_gb"),
                             "cache_reserva_gb": self.config.get("moe_cache_reserva_gb")})

    # ------------------------------------------------------------------ generar (en el servidor de Rust)
    # Generar es del servidor de Rust (prig_ia::generar): las opciones, el motor MoE, la recuperación de una falta de
    # memoria y el gobernador térmico viven allí. Estos métodos son sus clientes y conservan su forma de siempre.

    @staticmethod
    def _servidor_rust() -> Optional[str]:
        puerto = os.environ.get("PRIG_PUERTO_RUST")
        return f"http://127.0.0.1:{puerto}" if puerto else None

    def _flujo_rust(self, ruta: str, pedido: Dict[str, Any], cancelar: Optional[threading.Event]):
        """ Los eventos NDJSON de una generación en el servidor de Rust. Si se cancela (Detener, el cliente se fue),
        se cierra la conexión y el servidor deja de generar en el acto, también en mitad de una pausa térmica. """
        base = self._servidor_rust()
        if not base:
            raise ConnectionError("no hay servidor de Rust (PRIG_PUERTO_RUST)")
        res = requests.post(f"{base}{ruta}", json=pedido, stream=True, timeout=(5, None))
        with self._streams_lock:
            self._active_streams.add(res)
        parar = threading.Event()

        def vigia():
            while not parar.is_set():
                if cancelar.wait(0.2):
                    try:
                        res.close()
                    except Exception:
                        pass
                    return
        if cancelar is not None:
            threading.Thread(target=vigia, daemon=True, name="prig-vigia-generar").start()
        try:
            if res.status_code != 200:
                raise RuntimeError(f"Error del servidor {res.status_code}: {self._error_de(res)}")
            for linea in res.iter_lines():
                if linea:
                    yield json.loads(linea.decode("utf-8"))
        finally:
            parar.set()
            with self._streams_lock:
                self._active_streams.discard(res)
            try:
                res.close()
            except Exception:
                pass

    @staticmethod
    def _error_de(res) -> str:
        try:
            return (res.json().get("error") or "")[:300]
        except Exception:
            return (getattr(res, "text", "") or "")[:300]

    def motor_moe(self) -> "motor_moe.Motor":
        """ El motor MoE (cliente del servidor de Rust), con los modelos de Ollama que hay que soltarle y los ajustes """
        return motor_moe.motor(
            liberar_gpu=self._descargar_ollama,
            propios=self._modelos_de_prig_en_ollama,
            ajustes=lambda: {"contexto": self.config.get("moe_contexto"), "hilos": self.config.get("moe_hilos"),
                             "calientes": self.config.get("moe_calientes"), "modo": self.config.get("moe_modo"),
                             "mtp": self.config.get("moe_mtp", True), "nucleo": self.config.get("moe_nucleo"),
                             "cache_gb": self.config.get("moe_cache_gb"),
                             "cache_reserva_gb": self.config.get("moe_cache_reserva_gb")})

    def generar_con_pausas(
        self,
        prompt: str,
        model: str,
        system_prompt: str = "",
        options: Optional[Dict[str, Any]] = None,
        think: Optional[bool] = None,
        gobernador=None,
        cancelar: Optional[threading.Event] = None,
        avisar: Optional[Callable[[Dict[str, Any]], None]] = None,
        uso: Optional[str] = None,
    ) -> str:
        """ La respuesta completa, parando a enfriar la GPU cuando hace falta (con `gobernador`): se corta la conexión
        (eso enfría) y se continúa con lo ya escrito como inicio de la respuesta del asistente, sin perder nada.
        RuntimeError con el error de Ollama. Cancelada, devuelve "". """
        pedido = {"prompt": prompt, "model": model, "system_prompt": system_prompt, "options": options, "think": think,
                  "uso": uso, "gobernador": gobernador is not None, "con_avisos": avisar is not None}
        contenido = ""
        try:
            for ev in self._flujo_rust("/api/ia/pausas", pedido, cancelar):
                if ev.get("t") == "aviso" and avisar is not None:
                    avisar(ev.get("v") or {})
                elif ev.get("t") == "fin":
                    contenido = ev.get("v") or ""
                elif ev.get("t") == "error":
                    raise RuntimeError(ev.get("v") or "Error de Ollama")
        except RuntimeError:
            raise
        except Exception:
            if cancelar is not None and cancelar.is_set():
                return ""
            raise
        return contenido

    def chat_eventos(
        self,
        mensajes: List[Dict[str, Any]],
        model: str,
        uso: Optional[str] = "tutor",
        think: Optional[bool] = None,
        logprobs: int = 0,
        herramientas=None,
        max_rondas: int = 6,
        cancelar: Optional[threading.Event] = None,
        gobernador=None,
        extra: Optional[Dict[str, Any]] = None,
        max_tokens: Optional[int] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        """ Chat por eventos (texto, pensando, herramienta, resultado, logprobs, stats, aviso, error, termico), en el
        servidor de Rust (prig_ia::generar::chat_eventos). Las herramientas siguen aquí: el servidor pide ejecutar
        cada una (POST /api/interno/herramienta) mientras dura la respuesta. """
        if cancelar is None:
            cancelar = cancelacion_actual() or threading.Event()
        with self._streams_lock:
            self.__dict__.setdefault("_cancelables", set()).add(cancelar)
        sesion = None
        definiciones = None
        if herramientas is not None:
            definiciones = herramientas.definiciones()
            sesion = uuid.uuid4().hex
            SESIONES_HERRAMIENTAS[sesion] = herramientas
        pedido = {"mensajes": mensajes, "model": model, "uso": uso, "think": think, "logprobs": logprobs,
                  "max_rondas": max_rondas, "gobernador": gobernador is not None, "extra": extra,
                  "max_tokens": max_tokens,
                  "herramientas": {"sesion": sesion, "definiciones": definiciones or []} if sesion else None}
        try:
            for ev in self._flujo_rust("/api/ia/chat", pedido, cancelar):
                yield ev
        except Exception as e:
            if cancelar.is_set():
                yield {"t": "aviso", "v": "Detenido."}
            else:
                yield {"t": "error", "v": f"Error de conexión con Ollama: {e}"}
        finally:
            if sesion:
                SESIONES_HERRAMIENTAS.pop(sesion, None)
            with self._streams_lock:
                self._cancelables.discard(cancelar)

    def generate_response(
        self,
        prompt: str,
        model: str = "qwen2.5-coder:7b",
        system_prompt: str = "",
        options: Optional[Dict[str, Any]] = None,
        think: Optional[bool] = None,
        on_thinking: Optional[Callable[[str], None]] = None,
        on_token: Optional[Callable[[str], None]] = None,
        uso: Optional[str] = None,
        on_stats: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Generator[str, None, None]:
        """ La respuesta en trozos. `think` controla el razonamiento en voz alta de los modelos que lo traen; con
        `on_thinking` se pide si el modelo piensa. Con el gobernador térmico se genera por tramos y se sigue donde
        quedó (en el servidor de Rust). Los errores llegan como texto («[Error Ollama: …]»). """
        cancelar = cancelacion_actual() or threading.Event()
        with self._streams_lock:
            self.__dict__.setdefault("_cancelables", set()).add(cancelar)
        pedido = {"prompt": prompt, "model": model, "system_prompt": system_prompt, "options": options, "think": think,
                  "con_pensamiento": on_thinking is not None, "uso": uso,
                  "gobernador": getattr(self, "gobernador", None) is not None}
        try:
            for ev in self._flujo_rust("/api/ia/generar", pedido, cancelar):
                t = ev.get("t")
                if t == "texto":
                    if ev.get("token") and on_token:
                        on_token(ev["v"])
                    yield ev["v"]
                elif t == "pensando":
                    if on_thinking:
                        on_thinking(ev["v"])
                elif t == "stats":
                    if on_stats is not None:
                        on_stats(ev["v"])
        except Exception as e:
            if not cancelar.is_set():
                yield f"[Error de conexión con Ollama: {str(e)}]"
        finally:
            with self._streams_lock:
                self.__dict__.setdefault("_cancelables", set()).discard(cancelar)

    def cancel_active_requests(self) -> int:
        """ Cierra todas las conexiones HTTP activas con Ollama para detener la generación en GPU """
        with self._streams_lock:
            streams = list(self._active_streams)
            self._active_streams.clear()
            for evento in getattr(self, "_cancelables", ()):
                evento.set()
        count = 0
        for res in streams:
            try:
                res.close()
                count += 1
            except Exception:
                pass
        return count

    def unload_models(self) -> None:
        """ Libera la VRAM: los modelos de Ollama que cargó Prig (los de este proceso y los del servidor de Rust, que
        es quien genera) y el motor MoE """
        self._descargar_ollama()
        base = self._servidor_rust()
        if base:
            try:
                requests.post(f"{base}/api/ia/descargar", timeout=10)
            except Exception:
                pass
        try:
            self.motor_moe().detener()
        except Exception:
            pass

    def _modelos_de_prig_en_ollama(self) -> List[str]:
        """ Los modelos de Ollama que usa Prig (los que se descargan para dejarle la VRAM al motor MoE) """
        propios = set(getattr(self, "_usados", set()))
        propios |= {self.config.get(k) for k in ("agent1_model", "agent2_model", "agent3_model")}
        return sorted(m for m in propios if m and not motor_moe.es_moe(m))

    def _descargar_ollama(self) -> None:
        """ Libera la memoria VRAM descargando los modelos que Prig tiene cargados en Ollama.

        Antes solo se soltaban los de la configuración: uno elegido en el chat seguía
        ocupando la GPU hasta que vencía su keep_alive (30 min), ya con Prig cerrado.
        Los que cargó otro programa se dejan en paz.
        """
        propios = set(getattr(self, "_usados", set()))
        propios |= {self.config.get(k) for k in ("agent1_model", "agent2_model", "agent3_model")}
        try:
            cargados = [m.get("name") for m in requests.get(f"{self.base_url}/api/ps", timeout=2).json().get("models", [])]
        except Exception:
            cargados = [m for m in propios if m]
        for model in cargados:
            if model in propios:
                try:
                    requests.post(f"{self.base_url}/api/generate", json={"model": model, "keep_alive": 0}, timeout=2)
                except Exception:
                    pass

    def stop_ai_processes(self) -> None:
        """ Detiene peticiones de análisis activas y procesos de Ollama si Prig los inició """
        self.cancel_active_requests()
        try:
            self.motor_moe().detener()
        except Exception:
            pass
        # el `ollama serve` que arrancó Prig es del servidor de Rust
        puerto = os.environ.get("PRIG_PUERTO_RUST")
        if puerto:
            try:
                requests.post(f"http://127.0.0.1:{puerto}/api/ollama/detener", timeout=10)
            except Exception:
                pass

    # ==========================================
    # CONSULTA SOBRE LA BIBLIOTECA (RAG)
    # ==========================================

    def expand_query(self, query: str, model: str = "qwen2.5-coder:7b", max_variants: int = 3) -> List[str]:
        """ Genera reformulaciones para compensar el techo del recuperador léxico.

        BM25 y TF-IDF solo encuentran lo que comparte palabras con la consulta. Si el
        alumno pregunta "cómo evito el sobreajuste" y el libro dice "regularización
        L2", no hay ninguna palabra en común. Pedirle al modelo 2-3 reformulaciones
        con la terminología técnica recupera buena parte de esas coincidencias sin
        cambiar la arquitectura del índice.
        """
        sys_prompt = (
            "Reescribe la consulta del usuario en variantes de búsqueda con la TERMINOLOGÍA "
            "TÉCNICA equivalente que aparecería en un libro. Devuelve ÚNICAMENTE las variantes, "
            "una por línea, sin numerar, sin comillas y sin explicaciones. Máximo "
            f"{max_variants} líneas."
        )
        try:
            raw = "".join(self.generate_response(
                f"Consulta: {query}",
                model=model,
                system_prompt=sys_prompt,
                options={"temperature": 0.2}
            ))
        except Exception:
            return []

        variants = []
        for line in raw.splitlines():
            cleaned = line.strip().lstrip("-*0123456789.) ").strip().strip('"')
            if cleaned and cleaned.lower() != query.lower() and len(cleaned) > 3:
                variants.append(cleaned)
        return variants[:max_variants]

    LIBRARY_TUTOR_PROMPT = (
        "Eres el TUTOR de Prig IDE respondiendo a partir de la BIBLIOTECA PERSONAL del alumno.\n\n"
        "REGLAS ESTRICTAS:\n"
        "1. Responde APOYÁNDOTE en los fragmentos proporcionados. Son la fuente de verdad.\n"
        "2. Cita el fragmento que respalda cada afirmación con su marca [1], [2]...\n"
        "3. Si los fragmentos NO contienen la respuesta, dilo con claridad y explica qué falta. "
        "Es preferible admitirlo a inventar: el alumno debe poder confiar en las citas.\n"
        "4. Distingue explícitamente lo que viene de la biblioteca de lo que añades por tu cuenta.\n"
        "5. Responde en español, en Markdown limpio, sin saludos ni relleno."
    )

    def answer_from_library(
        self,
        query: str,
        context_prompt: str,
        model: str = "qwen2.5-coder:7b",
        mode: str = "chat"
    ) -> Generator[str, None, None]:
        """ Responde usando exclusivamente el contexto destilado de la biblioteca """
        if not context_prompt.strip():
            yield ("No encontré nada en tu biblioteca relacionado con esa consulta. "
                   "Comprueba que el material esté indexado en la sección de Biblioteca.")
            return

        depth = self.config.get("depth_level", "intermediate")
        sys_prompt = f"{self.LIBRARY_TUTOR_PROMPT}\n\nNivel del alumno: {depth}."

        prompt = f"{context_prompt}\n\n---\nPREGUNTA DEL ALUMNO: {query}"
        for chunk in self.generate_response(prompt, model=model, system_prompt=sys_prompt):
            yield chunk

    # ==========================================
    # PROMPTS DEL TUTOR Y EJECUCIÓN DE WORKFLOWS MULTI-AGENTE
    # ==========================================

    TUTOR_BASE_PROMPT = (
        "Eres el TUTOR DE IA de Prig IDE, un entorno de desarrollo local orientado al "
        "aprendizaje de programación, ciencia de datos e inteligencia artificial. "
        "Respondes en español, en Markdown limpio (títulos ##, listas y bloques ```lenguaje), "
        "sin saludos ni relleno. Prefieres ejemplos ejecutables y concretos sobre la teoría vaga."
    )

    TUTOR_MODE_PROMPTS = {
        "chat": "Responde de forma directa y didáctica a la consulta del alumno.",
        "explain": (
            "Explica el código o contenido proporcionado: cuál es su propósito, cómo está "
            "estructurado y qué hace cada parte relevante. Termina con los puntos clave a recordar."
        ),
        "explain_flow": (
            "Explica el FLUJO DE EJECUCIÓN paso a paso: qué ocurre en cada línea, cómo cambian "
            "los datos y en qué orden. Si el flujo tiene ramas o ciclos, añade un diagrama "
            "```mermaid``` que lo represente."
        ),
        "debug": (
            "Actúa como depurador. Identifica la causa raíz del error, explica por qué ocurre "
            "y entrega el código corregido completo en un bloque de código."
        ),
        "diagnose_error": (
            "Has recibido un traceback o mensaje de error. Indica (1) qué significa el error, "
            "(2) cuál es la causa más probable en este código y (3) la corrección concreta. "
            "Si el contexto incluye documentación oficial de internet, cítala."
        ),
        "optimize": (
            "Revisa el código y propón mejoras de legibilidad, rendimiento y buenas prácticas. "
            "Justifica cada cambio y entrega la versión mejorada."
        ),
        "review": (
            "Haz una revisión de código: correcciones necesarias, riesgos y sugerencias, "
            "ordenadas por importancia."
        ),
        "tutor": (
            "Actúa como profesor guía: no des la solución completa de golpe, conduce al alumno "
            "con explicaciones y preguntas hasta que pueda resolverlo."
        ),
    }

    def get_tutor_system_prompt(self, mode: str = "chat") -> str:
        """ System prompt del tutor según el modo de interacción de la interfaz """
        mode_prompt = self.TUTOR_MODE_PROMPTS.get(mode or "chat", self.TUTOR_MODE_PROMPTS["chat"])

        depth = self.config.get("depth_level", "intermediate")
        depth_prompt = {
            "basic": "Nivel del alumno: principiante. Prioriza los conceptos fundamentales, evita la jerga y sé breve.",
            "intermediate": "Nivel del alumno: intermedio. Equilibra teoría y práctica con ejemplos reales.",
            "advanced": "Nivel del alumno: avanzado. Profundiza en detalles de implementación, rendimiento y matices.",
            "expert": "Nivel del alumno: experto. Céntrate en arquitectura, rendimiento en producción y compromisos de diseño."
        }.get(depth, "Nivel del alumno: intermedio. Equilibra teoría y práctica con ejemplos reales.")

        return f"{self.TUTOR_BASE_PROMPT}\n\n{mode_prompt}\n\n{depth_prompt}"

    ROLE_SYSTEM_PROMPTS = {
        "programmer": (
            "Eres un ingeniero de software senior. Entregas código completo, ejecutable y "
            "comentado, sin pseudocódigo ni fragmentos incompletos."
        ),
        "reviewer": (
            "Eres un revisor de código exigente. Señalas errores, riesgos y mejoras concretas "
            "sobre la entrada recibida, y devuelves la versión corregida."
        ),
        "architect": (
            "Eres un arquitecto de software. Diseñas la estructura, los módulos y las decisiones "
            "técnicas antes de entrar en el código."
        ),
        "analyst": (
            "Eres un analista de datos. Interpretas la entrada, extraes conclusiones y las "
            "respaldas con cifras o evidencias."
        ),
        "writer": (
            "Eres un redactor técnico. Conviertes la entrada en documentación clara y estructurada "
            "en Markdown."
        ),
        "tester": (
            "Eres un ingeniero de QA. Diseñas y escribes pruebas que cubran los casos normales, "
            "los límites y los errores del código recibido."
        ),
    }

    def run_workflow_step(
        self,
        prompt: str,
        model: str = "qwen2.5-coder:7b",
        role: str = "programmer",
        temperature: Optional[float] = 0.3,
        custom_sys_prompt: str = ""
    ) -> str:
        """ Ejecuta un paso del workflow multi-agente y devuelve el texto completo del agente """
        sys_prompt = custom_sys_prompt.strip() if custom_sys_prompt else ""
        if not sys_prompt:
            sys_prompt = self.ROLE_SYSTEM_PROMPTS.get(role, self.ROLE_SYSTEM_PROMPTS["programmer"])

        parts = []
        try:
            for chunk in self.generate_response(
                prompt,
                model=model,
                system_prompt=sys_prompt,
                options={"temperature": temperature}
            ):
                parts.append(chunk)
        except Exception as err:
            return f"[Error ejecutando el agente '{role}' con el modelo {model}: {err}]"

        return "".join(parts).strip()




    @classmethod
    def _extract_and_parse_json(cls, *args, **kwargs) -> dict:
        text = kwargs.get("response_text") or (args[-1] if args else "")
        return reparar_y_parsear_json(text)

    def run_knowledge_architect(
        self,
        user_goal: str,
        library_items: list,
        model: str = "qwen2.5-coder:7b",
        on_thinking: Optional[Callable[[str], None]] = None,
        on_token: Optional[Callable[[str], None]] = None
    ) -> dict:
        sources_summary = []
        for item in library_items[:20]:
            sources_summary.append({
                "source_id": item.get("id"),
                "title": item.get("title"),
                "type": item.get("category_id") or item.get("ext"),
                "topics": item.get("metadata", {}).get("topics", []) if item.get("metadata") else []
            })
        sys_prompt = """Eres el AGENTE 1: KNOWLEDGE ARCHITECT.
Tu tarea es descomponer el objetivo del alumno en un mapa de conocimiento jerárquico
(dominios -> temas -> conceptos) apoyándote en las fuentes de la biblioteca que recibes.

REGLAS:
1. Cada concept_id, topic_id y domain_id debe ser único y en snake_case (ej: conc_tensores).
2. Las relaciones y prerrequisitos solo pueden referenciar concept_id que existan en domains.
3. Cita en evidence el source_id de la fuente de la biblioteca que respalda cada concepto.

Devuelve ÚNICAMENTE un objeto JSON válido, sin texto ni markdown alrededor, con esta forma:
{
  "goal": "objetivo del alumno",
  "domains": [
    {
      "domain_id": "dom_01",
      "name": "Nombre del dominio",
      "topics": [
        {
          "topic_id": "top_01",
          "name": "Nombre del tema",
          "concepts": [
            {
              "concept_id": "conc_01",
              "name": "Nombre del concepto",
              "specifications": "Qué debe dominar exactamente el alumno",
              "concept_type": "THEORETICAL",
              "evidence": [{"source_id": "archivo.pdf", "title": "Título del documento", "location": "cap. 3"}]
            }
          ]
        }
      ]
    }
  ],
  "prerequisites": [{"name": "Álgebra lineal básica", "reason": "por qué hace falta", "required": true}],
  "relationships": [{"source_concept_id": "conc_01", "target_concept_id": "conc_02", "relation_type": "REQUIRES"}]
}"""
        prompt = f"Objetivo: '{user_goal}'\nFuentes disponibles en la biblioteca: {json.dumps(sources_summary, ensure_ascii=False)}"
        response_text = ""
        for chunk in self.generate_response(prompt, model=model, system_prompt=sys_prompt, on_thinking=on_thinking, on_token=on_token):
            response_text += chunk
        return self._extract_and_parse_json(response_text)

    def run_practice_architect(
        self,
        knowledge_map: dict,
        model: str = "qwen2.5-coder:7b",
        on_thinking: Optional[Callable[[str], None]] = None,
        on_token: Optional[Callable[[str], None]] = None
    ) -> dict:
        sys_prompt = """Eres el AGENTE 2: PRACTICE & CURRICULUM ARCHITECT.
Recibes un KNOWLEDGE_MAP y lo conviertes en un currículo práctico: módulos ordenados,
cada uno con un objetivo, criterios de validación comprobables y tareas concretas.

REGLAS:
1. Los module_id siguen el formato mod_01, mod_02, ... en orden de dificultad creciente.
2. El campo concepts de cada módulo SOLO puede contener concept_id existentes en el KNOWLEDGE_MAP.
3. Cada validation_criteria debe ser verificable por el alumno ("ejecuta X y obtén Y"), no vago.

Devuelve ÚNICAMENTE un objeto JSON válido, sin texto ni markdown alrededor, con esta forma:
{
  "curriculum_id": "curr_01",
  "goal": "objetivo del alumno",
  "modules": [
    {
      "module_id": "mod_01",
      "name": "Nombre del módulo",
      "objective": "Qué sabrá hacer el alumno al terminarlo",
      "concepts": ["conc_01", "conc_02"],
      "validation_criteria": ["Criterio comprobable 1", "Criterio comprobable 2"],
      "tasks": [{"task_id": "task_01", "description": "Qué debe programar o resolver"}]
    }
  ],
  "objectives": ["Objetivo global 1", "Objetivo global 2"],
  "module_dependencies": [{"from_module_id": "mod_01", "to_module_id": "mod_02"}]
}"""
        prompt = f"KNOWLEDGE_MAP:\n{json.dumps(knowledge_map, ensure_ascii=False)}"
        response_text = ""
        for chunk in self.generate_response(prompt, model=model, system_prompt=sys_prompt, on_thinking=on_thinking, on_token=on_token):
            response_text += chunk
        return self._extract_and_parse_json(response_text)

    def run_notebook_manager(
        self,
        practical_curriculum: dict,
        library_code_items: list,
        model: str = "qwen2.5-coder:7b",
        on_thinking: Optional[Callable[[str], None]] = None,
        on_token: Optional[Callable[[str], None]] = None
    ) -> dict:
        code_summary = [{"id": item.get("id"), "filename": item.get("filename")} for item in library_code_items[:15]]
        sys_prompt = """Eres el AGENTE 3: NOTEBOOK & LEARNING MANAGER.
Recibes un currículo práctico y el listado de cuadernos y código disponibles en la
biblioteca, y planificas qué cuaderno ejecutable corresponde a cada módulo.

REGLAS:
1. Cada module_id debe existir en el currículo recibido; no inventes módulos nuevos.
2. source_library_notebook debe ser una ruta exacta del listado de la biblioteca, o null
   si el cuaderno se crea desde cero.
   action solo admite dos valores: CREATED_FROM_SCRATCH o COPIED_AND_EXPLAINED.
3. Nunca propongas escribir dentro de la biblioteca: las copias editables las genera el sistema.

Devuelve ÚNICAMENTE un objeto JSON válido, sin texto ni markdown alrededor, con esta forma:
{
  "plan_id": "exec_01",
  "goal": "objetivo del alumno",
  "modules_notebooks": [
    {
      "module_id": "mod_01",
      "module_name": "Nombre del módulo",
      "notebooks": [
        {
          "notebook_id": "nb_01",
          "title": "Título del cuaderno",
          "executable_path": "",
          "action": "CREATED_FROM_SCRATCH",
          "source_library_notebook": null,
          "description": "Qué se practica en este cuaderno"
        }
      ]
    }
  ],
  "total_notebooks_copied_and_edited": 0,
  "total_notebooks_created": 1
}"""
        prompt = (
            f"CURRICULUM:\n{json.dumps(practical_curriculum, ensure_ascii=False)}\n\n"
            f"CUADERNOS Y CÓDIGO DISPONIBLES EN LA BIBLIOTECA:\n{json.dumps(code_summary, ensure_ascii=False)}"
        )
        response_text = ""
        for chunk in self.generate_response(prompt, model=model, system_prompt=sys_prompt, on_thinking=on_thinking, on_token=on_token):
            response_text += chunk
        return self._extract_and_parse_json(response_text)

    def interpret_change_request(self, user_prompt: str, current_stage: str, model: str = "qwen2.5-coder:7b") -> dict:
        sys_prompt = """Eres el ASISTENTE DISEÑADOR DEL PLAN.
Traduces la petición en lenguaje natural del alumno a una orden de cambio estructurada
sobre el plan de estudio que está revisando.

target_agent válidos: KNOWLEDGE_ARCHITECT | PRACTICE_ARCHITECT | NOTEBOOK_MANAGER
action válidos: ADD_PREREQUISITE | REMOVE_PREREQUISITE | ADD_CONCEPT | REMOVE_CONCEPT |
                ADD_TOPIC | MODIFY_OBJECTIVE | ADD_PRACTICAL_MODULE

Devuelve ÚNICAMENTE un objeto JSON válido, sin texto ni markdown alrededor, con esta forma:
{
  "target_agent": "KNOWLEDGE_ARCHITECT",
  "action": "ADD_PREREQUISITE",
  "target": "Nombre exacto del elemento afectado",
  "parameter": "Valor adicional si aplica, o cadena vacía",
  "reason": "Por qué se aplica este cambio"
}"""
        prompt = f"Etapa actual del plan: {current_stage}\nPetición del alumno: '{user_prompt}'"
        response_text = ""
        for chunk in self.generate_response(prompt, model=model, system_prompt=sys_prompt):
            response_text += chunk
        return self._extract_and_parse_json(response_text)

    def run_topic_organizer(
        self,
        goal: str,
        topics: str,
        level: str = "Intermedio",
        focus: str = "Práctico",
        model: str = "qwen2.5-coder:7b",
        on_thinking: Optional[Callable[[str], None]] = None,
        on_token: Optional[Callable[[str], None]] = None,
        on_stage: Optional[Callable[[str, int], None]] = None
    ) -> dict:
        if on_stage:
            on_stage("Analizando temas pedagógicos y preparando directivas...", 25)
        sys_prompt = f"""Eres el AGENTE ORGANIZADOR DE TEMAS EXPERTO EN PEDAGOGÍA.
Tu trabajo es tomar una meta y una lista desordenada de temas y organizarlos en un plan de aprendizaje secuencial (estilo Roadmap.sh o Duolingo). 

PARÁMETROS DEL ESTUDIANTE:
- Nivel Objetivo: {level}
- Enfoque Pedagógico: {focus}

REGLAS PEDAGÓGICAS:
1. "Chunking": Divide los temas en bloques pequeños y digeribles (microaprendizaje).
2. Progresión: Adapta los temas al nivel ({level}) y el enfoque ({focus}).
3. Todo bloque debe tener un `learning_objective` claro (qué logrará el estudiante).
4. Todo bloque debe tener un `validation_check` claro (un pequeño proyecto, test o acción para probar que lo aprendió).
        
Debes devolver ÚNICAMENTE un objeto JSON válido con la siguiente estructura:
{{
  "goal": "La meta a alcanzar",
  "blocks": [
    {{
      "title": "Nombre del bloque",
      "description": "Qué se debe lograr aquí",
      "learning_objective": "Competencia a adquirir (Ej: Ser capaz de crear un servidor local)",
      "validation_check": "Hito práctico (Ej: Inicializa un script que devuelva 'Hola' en localhost:8080)",
      "topics": ["tema1", "tema2"],
      "type": "theory | practice | project | mixed",
      "estimated_time": "ej: 2 horas"
    }}
  ],
  "rationale": "Explicación breve de por qué los organizaste así basándote en pedagogía"
}}"""
        prompt = f"Meta: {goal}\nTemas:\n{topics}\nNivel: {level}\nEnfoque: {focus}"
        response_text = ""
        started_generating = False

        def _handle_token(token_str: str):
            nonlocal started_generating
            if not started_generating:
                started_generating = True
                if on_stage:
                    on_stage("El modelo está deduciendo la progresión pedagógica y redactando los bloques...", 55)
            if on_token:
                on_token(token_str)

        for chunk in self.generate_response(
            prompt,
            model=model,
            system_prompt=sys_prompt,
            on_thinking=on_thinking,
            on_token=_handle_token
        ):
            response_text += chunk

        if on_stage:
            on_stage("Estructurando bloques pedagógicos y validando formato...", 88)
        parsed = self._extract_and_parse_json(response_text)
        if not isinstance(parsed, dict):
            parsed = {"goal": goal, "blocks": [], "rationale": "Respuesta recibida."}

        if "blocks" not in parsed or not isinstance(parsed["blocks"], list):
            parsed["blocks"] = []

        parsed["goal"] = goal
        for i, b in enumerate(parsed["blocks"]):
            if not isinstance(b, dict):
                continue
            if "title" not in b or not b["title"]:
                b["title"] = f"Bloque {i+1}"
            if "description" not in b or not b["description"]:
                b["description"] = f"Estudio práctico del bloque {i+1}."
            if "topics" not in b or not isinstance(b["topics"], list):
                if isinstance(b.get("topics"), str):
                    b["topics"] = [b["topics"]]
                else:
                    b["topics"] = ["Tema General"]
            if "type" not in b or b["type"] not in ["theory", "practice", "project", "mixed"]:
                b["type"] = "practice"

        return parsed

    def generate_block_quiz(self, goal: str, block: dict, model: str = "qwen2.5-coder:7b") -> dict:
        sys_prompt = """Eres un GENERADOR DE QUIZZES PEDAGÓGICOS INTERACTIVOS.
Genera un Quiz de Autoevaluación corto de 3 preguntas de opción múltiple para verificar que el estudiante comprendió este bloque.

Debes devolver ÚNICAMENTE un objeto JSON válido con este formato:
{
  "block_title": "Título del Bloque",
  "questions": [
    {
      "id": 1,
      "question": "Pregunta clara sobre el tema",
      "options": ["Opción A", "Opción B", "Opción C", "Opción D"],
      "correct_index": 0,
      "explanation": "Explicación de por qué la respuesta correcta es esa"
    }
  ]
}"""
        prompt = f"Meta: {goal}\nBloque: {block.get('title')}\nTemas: {', '.join(block.get('topics', []))}\nObjetivo: {block.get('learning_objective')}"
        response_text = ""
        for chunk in self.generate_response(prompt, model=model, system_prompt=sys_prompt):
            response_text += chunk
        return self._extract_and_parse_json(response_text)


    def generate_response_with_web_search(self, user_prompt: str, model: str = "qwen2.5-coder:7b", system_prompt: str = "") -> Generator[str, None, None]:
        web_context, sources = self.web_search.get_web_context(user_prompt)
        full_prompt = f"{user_prompt}\n\n{web_context}" if web_context else user_prompt
        
        sys_p = system_prompt or "Eres un asistente de IA experto. Utiliza la información y documentación oficial de internet adjunta para responder con la máxima precisión, detalle y ejemplos."
        
        for chunk in self.generate_response(full_prompt, model=model, system_prompt=sys_p):
            yield chunk
            
        if sources:
            yield "\n\n---\n**🌐 Fuentes Oficiales de Internet Consultadas:**\n"
            for s in sources:
                yield f"- [{s['title']}]({s['url']}) (`{s['domain']}`)\n"

    def explain_seguimiento_block(self, goal: str, block: dict, model: str = "qwen2.5-coder:7b", use_web: bool = True,
                                  contexto_extra: str = ""):
        web_context = ""
        sources = []
        if use_web:
            topics_str = " ".join(block.get('topics', []))
            query = f"{block.get('title', '')} {topics_str}"
            web_context, sources = self.web_search.get_web_context(query)

        sys_prompt = """Eres un TUTOR DE INTELIGENCIA ARTIFICIAL EXPERTO EN PROGRAMACIÓN Y TECNOLOGÍA.
Tu objetivo es dar una clase magistral profunda y detallada sobre un bloque de temas de una ruta de aprendizaje.
Sintoniza y profundiza la clase utilizando tanto tu conocimiento como la INFORMACIÓN Y DOCUMENTACIÓN OFICIAL DE INTERNET obtenida.

REGLAS PEDAGÓGICAS PARA TU RESPUESTA:
1. Explica los conceptos de forma clara, amena y profunda. Usa ejemplos de código reales.
2. Si los temas involucran flujos, lógica, secuencias o arquitectura, genera un DIAGRAMA VISUAL en sintaxis MERMAID (usando ```mermaid ... ```).
3. Integra sintaxis y mejores prácticas oficiales del contexto de internet si corresponden.
4. Si el contexto incluye enlaces o recursos oficiales, cítalos explícitamente.
5. Tu respuesta debe estar formateada en Markdown (títulos ##, ###, bloques de código ```).
"""
        prompt = f"Meta del Alumno: {goal}\n\nBloque a Explicar:\n- Título: {block.get('title')}\n- Temas: {', '.join(block.get('topics', []))}\n- Objetivo: {block.get('learning_objective')}\n- Validación: {block.get('validation_check')}\n\n{web_context}\n{contexto_extra}\n¡Por favor, dame la clase!"
        
        for chunk in self.generate_response(prompt, model=model, system_prompt=sys_prompt):
            yield chunk

        if sources:
            yield "\n\n---\n**🌐 Fuentes Oficiales de Internet Consultadas:**\n"
            for s in sources:
                yield f"- [{s['title']}]({s['url']}) (`{s['domain']}`)\n"

    def generate_challenge_for_block(self, goal: str, block: dict, model: str = "qwen2.5-coder:7b") -> dict:
        """ Genera un reto de código práctico para verificar las competencias del bloque """
        sys_prompt = """Eres un EVALUADOR TÉCNICO DE PROGRAMACIÓN.
Genera un RETO DE CÓDIGO PRÁCTICO en formato JSON estricto con el siguiente esquema exacto:
{
  "challenge_title": "Título del reto",
  "instructions": "Instrucciones detalladas paso a paso sobre lo que el alumno debe programar",
  "starter_code": "# Código inicial de plantilla para completar\\ndef mi_funcion():\\n    # TODO: Implementar aquí\\n    pass",
  "expected_output_hint": "Pista del resultado esperado o prueba de ejecución"
}"""
        prompt = f"Meta del Alumno: {goal}\nBloque: {block.get('title')}\nTemas: {', '.join(block.get('topics', []))}\nObjetivo: {block.get('learning_objective')}"
        res_text = ""
        for chunk in self.generate_response(prompt, model=model, system_prompt=sys_prompt):
            res_text += chunk
        return self._extract_and_parse_json(res_text)

    def verify_user_code_solution(self, goal: str, block: dict, user_code: str, model: str = "qwen2.5-coder:7b") -> dict:
        """ Evalúa la solución de código enviada por el alumno y entrega retroalimentación paso a paso """
        sys_prompt = """Eres un REVISOR DE CÓDIGO TÉCNICO Y EVALUADOR PEDAGÓGICO.
Evalúa el código del alumno para el objetivo dado y responde con un JSON estricto:
{
  "passed": true / false,
  "score": 0 a 100,
  "feedback": "Explicación detallada y constructiva sobre el código",
  "suggestions": ["Sugerencia 1", "Sugerencia 2"],
  "corrected_code": "Código corregido o mejorado (opcional si aprobó)"
}"""
        prompt = f"Meta: {goal}\nBloque: {block.get('title')}\nObjetivo: {block.get('learning_objective')}\nValidación Esperada: {block.get('validation_check')}\n\nCÓDIGO DEL ALUMNO:\n```python\n{user_code}\n```"
        res_text = ""
        for chunk in self.generate_response(prompt, model=model, system_prompt=sys_prompt):
            res_text += chunk
        return self._extract_and_parse_json(res_text)


