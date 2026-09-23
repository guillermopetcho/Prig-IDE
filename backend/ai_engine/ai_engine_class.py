import os
import sys
import json
import time
import re
import shutil
import subprocess
import threading
import requests
import ast
from typing import Dict, Any, Generator, List, Optional, Callable
# Import relativo: el absoluto solo funcionaba con backend/ en sys.path y rompía
# al importar el paquete como backend.ai_engine (p. ej. desde los tests).
from .web_search_engine import WebSearchEngine

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
CONFIG_PATH = os.path.expanduser("~/.prig_ai_config.json")


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
            "exec_timeout": 25
        }
        self._load_config()

    def _load_config(self) -> None:
        """ La configuración se guardaba solo en memoria y se perdía al reiniciar """
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                for k, v in saved.items():
                    if k in self.config and v is not None:
                        self.config[k] = v
                if saved.get("ollama_url"):
                    self.base_url = saved["ollama_url"]
        except Exception as e:
            print(f"⚠️ No se pudo leer la configuración de IA guardada: {e}")

    def _save_config(self) -> None:
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ No se pudo guardar la configuración de IA: {e}")

    def get_config(self) -> Dict[str, Any]:
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
        best = self.get_best_ollama_binary()
        best_bin = best[0] if best else None
        best_ver = best[1] if best else "0.0.0"

        # 1. Comprobar si ya hay una instancia respondiendo
        active_ver = None
        try:
            res = requests.get(f"{self.base_url}/api/version", timeout=2)
            if res.status_code == 200:
                active_ver = res.json().get("version")
        except Exception:
            pass

        # Si ya responde y no se fuerza reinicio:
        # Verificar si la versión activa es obsoleta respecto al mejor binario disponible
        if active_ver and not force_restart:
            en_marcha = self.binario_ollama_en_marcha()
            roto = (en_marcha is not None and best_bin is not None
                    and os.path.realpath(en_marcha) != os.path.realpath(best_bin)
                    and estado_runtime_ollama(en_marcha) == RUNTIME_INCOMPLETO
                    and estado_runtime_ollama(best_bin) == RUNTIME_COMPLETO)
            if roto:
                # Responde, pero no puede cargar modelos: se cambia por el completo
                print(f"⚠️ {en_marcha} no tiene llama-server; se reinicia Ollama con {best_bin}")
            elif best_ver and self._version_ge(active_ver, best_ver):
                return True
            # El binario local es más moderno (o el activo está roto): forzar reinicio
            force_restart = True

        if force_restart:
            self.kill_ollama_processes()

        if not best_bin:
            return False

        # Iniciar el mejor binario con serve
        try:
            env = os.environ.copy()
            # Variables del servidor elegidas en "Recomendado" (caché KV, ranuras…)
            try:
                from recursos.servidor import entorno_arranque
                env = entorno_arranque(env)
            except Exception as e:
                print(f"⚠️ No se pudieron leer los ajustes de servidor guardados: {e}")
            prig_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            bin_dir = os.path.dirname(best_bin)
            env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"

            ollama_home = os.path.expanduser("~/.ollama")
            try:
                os.makedirs(ollama_home, exist_ok=True)
            except Exception:
                local_models = os.path.join(prig_root, ".ollama")
                try:
                    os.makedirs(local_models, exist_ok=True)
                    env["OLLAMA_MODELS"] = os.path.join(local_models, "models")
                except Exception:
                    pass

            # La salida va a ~/.prig_ollama.log (Modelos → Servidor → Registro)
            registro = None
            try:
                from recursos.servidor import abrir_registro
                registro = abrir_registro()
            except Exception:
                registro = None
            self._ollama_proc = subprocess.Popen(
                [best_bin, "serve"],
                env=env,
                stdout=registro or subprocess.DEVNULL,
                stderr=subprocess.STDOUT if registro else subprocess.DEVNULL
            )

            # Esperar a que el servidor responda (hasta 6 segundos)
            for _ in range(12):
                time.sleep(0.5)
                try:
                    res = requests.get(f"{self.base_url}/api/version", timeout=1)
                    if res.status_code == 200:
                        return True
                except Exception:
                    pass
        except Exception as e:
            print(f"Error intentando iniciar Ollama con {best_bin}: {e}")

        return False

    def check_health(self) -> Dict[str, Any]:
        self.try_autostart_ollama()
        try:
            res = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if res.status_code == 200:
                models = [m["name"] for m in res.json().get("models", [])]
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
                return {"online": True, "models": detailed, "version": ver, "url": self.base_url}
            return {"online": False, "models": [], "version": ver, "message": f"HTTP {res.status_code}"}
        except Exception as e:
            return {"online": False, "models": [], "version": ver, "message": str(e)}

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

    def _post_con_recuperacion(self, url: str, payload: Dict[str, Any], intentos: int = 3):
        """ POST a Ollama que sobrevive a una falta de memoria al cargar.

        Si el modelo no cabe con estas opciones (otro programa ocupó la GPU, un
        contexto demasiado grande), se reintenta con menos contexto y después menos
        capas en GPU, en lugar de devolver un error al usuario. Lo que funcionó se
        anota en los eventos de recursos.
        """
        if payload.get("model"):
            self.__dict__.setdefault("_usados", set()).add(payload["model"])
        for n in range(intentos + 1):
            res = requests.post(url, json=payload, stream=True, timeout=300)
            with self._streams_lock:
                self._active_streams.add(res)
            if res.status_code == 200 or n == intentos:
                return res
            detalle = self._error_de(res)
            try:
                from recursos.gestor import gestor
                siguiente = gestor().recuperar_oom(payload.get("model", ""),
                                                   payload.get("options") or {}, detalle)
            except Exception:
                siguiente = None
            if siguiente is None:
                return res
            with self._streams_lock:
                self._active_streams.discard(res)
            res.close()
            opciones = dict(payload.get("options") or {})
            opciones.pop("num_gpu", None)
            opciones.update(siguiente)
            payload = {**payload, "options": opciones}
            print(f"⚠️ {payload.get('model')} sin memoria; reintentando con {siguiente}")
        return res

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
        """ Genera la respuesta completa, parando a enfriar la GPU cuando hace falta.

        Usa /api/chat porque permite CONTINUAR: si hay que cortar a mitad, lo ya
        generado se reenvía como principio de la respuesta del asistente y el modelo
        sigue desde ahí. Ollama reaprovecha la caché del prefijo, así que retomar
        cuesta milisegundos y no se pierde nada de lo generado.

        Cortar la conexión detiene la generación en Ollama (medido: el consumo de la
        GPU cae de 40 a 15 W en 1,5 s), que es lo que de verdad la enfría.

        Si se corta durante el razonamiento de un modelo que piensa, al retomar
        Ollama cierra ese razonamiento y pasa a la respuesta: se avisa.
        """
        url = f"{self.base_url}/api/chat"
        opciones = self._build_options(options, model, uso)
        tope = int(opciones.get("num_predict") or 0)
        base: Dict[str, Any] = {}
        sistema = self._completar_payload(base, model, uso, think, system_prompt)["sistema"]
        think = base.get("think")
        mensajes: List[Dict[str, Any]] = []
        if sistema:
            mensajes.append({"role": "system", "content": sistema})
        mensajes.append({"role": "user", "content": prompt})
        contenido, pensamiento = "", ""
        generados = 0
        keep_alive = base.get("keep_alive")
        monitor = gobernador.monitor.trabajando() if gobernador is not None else None
        if monitor is not None:
            monitor.__enter__()
        try:
            while True:
                if cancelar is not None and cancelar.is_set():
                    break
                payload: Dict[str, Any] = {"model": model, "stream": True,
                                           "options": dict(opciones),
                                           **{k: base[k] for k in ("truncate", "shift") if k in base}}
                if tope > 0:
                    payload["options"]["num_predict"] = max(1, tope - generados)
                if keep_alive is not None:
                    payload["keep_alive"] = keep_alive
                if think is not None:
                    payload["think"] = bool(think)
                if options and options.get("format"):
                    payload["format"] = options.get("format")
                previo = []
                if contenido or pensamiento:
                    asistente: Dict[str, Any] = {"role": "assistant", "content": contenido}
                    if pensamiento:
                        asistente["thinking"] = pensamiento
                    previo = [asistente]
                payload["messages"] = mensajes + previo

                tramo = gobernador.empezar_tramo() if gobernador is not None else None
                res = self._post_con_recuperacion(url, payload)
                motivo, terminado = None, False
                ultimo_control = time.time()
                try:
                    if res.status_code != 200:
                        raise RuntimeError(f"Error Ollama {res.status_code}: {self._error_de(res)}")
                    for linea in res.iter_lines():
                        if not linea:
                            continue
                        datos = json.loads(linea.decode("utf-8"))
                        if datos.get("error"):
                            raise RuntimeError(datos["error"])
                        msg = datos.get("message") or {}
                        if msg.get("thinking"):
                            pensamiento += msg["thinking"]
                            generados += 1
                        if msg.get("content"):
                            contenido += msg["content"]
                            generados += 1
                        if datos.get("done"):
                            terminado = True
                            break
                        if cancelar is not None and cancelar.is_set():
                            break
                        ahora = time.time()
                        if gobernador is not None and ahora - ultimo_control >= 1.0:
                            ultimo_control = ahora
                            motivo = gobernador.debe_cortar(tramo)
                            if motivo == "ritmo" and msg.get("thinking") and not msg.get("content"):
                                motivo = None
                            if motivo:
                                break
                finally:
                    with self._streams_lock:
                        self._active_streams.discard(res)
                    try:
                        res.close()
                    except Exception:
                        pass

                if terminado or not motivo or (tope > 0 and generados >= tope):
                    if gobernador is not None:
                        gobernador.terminar_tramo(tramo, motivo)
                    break
                if avisar is not None and not contenido and pensamiento and motivo != "ritmo":
                    avisar({"tipo": "aviso_termico",
                            "mensaje": "Pausa durante el razonamiento: al retomar, el modelo "
                                       "cerrará ese razonamiento y pasará a responder."})
                gobernador.enfriar(motivo, cancelar, avisar, tramo=tramo)
                gobernador.terminar_tramo(tramo, motivo)
        finally:
            if monitor is not None:
                monitor.__exit__(None, None, None)
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
    ) -> Generator[Dict[str, Any], None, None]:
        """ Chat por eventos: texto, razonamiento, herramientas, confianza y métricas.

          {"t": "texto", "v": "…"}            parte de la respuesta
          {"t": "pensando", "v": "…"}         parte del razonamiento
          {"t": "herramienta", "nombre", "argumentos"}
          {"t": "resultado", "nombre", "v"}
          {"t": "logprobs", "v": [...]}       probabilidad de cada token
          {"t": "stats", "v": {...}}          métricas al terminar
          {"t": "aviso" | "error", "v": "…"}
          {"t": "termico", "v": "…", "pausa": bool}   pausa para enfriar la GPU y reanudación

        Si el último mensaje es del asistente, el modelo lo CONTINÚA (verificado): es
        lo que permite "Continuar" una respuesta cortada por el límite de tokens.

        Con `gobernador`, el chat respeta el límite de temperatura igual que los flujos:
        corta la generación al acercarse, espera a que la GPU baje y la continúa con lo
        ya escrito como prefijo del asistente (no se pierde nada).
        """
        url = f"{self.base_url}/api/chat"
        opciones = self._build_options(None, model, uso)
        base: Dict[str, Any] = {}
        extra = self._completar_payload(base, model, uso, think, "")["sistema"]
        msgs = [dict(m) for m in mensajes]
        if extra:
            if msgs and msgs[0].get("role") == "system":
                msgs[0]["content"] = f"{msgs[0]['content']}\n\n{extra}"
            else:
                msgs.insert(0, {"role": "system", "content": extra})
        caps = self.capacidades(model)
        definiciones = herramientas.definiciones() if herramientas is not None else None
        if definiciones and "tools" not in caps:
            yield {"t": "aviso", "v": f"{model} no admite herramientas: responde sin ellas."}
            definiciones = None
        if think and "thinking" not in caps:
            yield {"t": "aviso", "v": f"{model} no razona antes de responder."}

        def enfriar(motivo):
            """ Espera a que la GPU baje, contando lo que pasa en el chat """
            if motivo == "ritmo":
                gobernador.descansar(tramo, cancelar)      # modo suave: pausa corta y sin avisos
                return
            temp = gobernador.monitor.gpu(max_edad=1.0)
            if temp is None or temp <= gobernador.reanudar:
                return
            yield {"t": "termico", "pausa": True,
                   "v": f"GPU a {temp:.0f} °C (límite {gobernador.limite:.0f} °C): pausa para enfriar; "
                        f"se sigue a {gobernador.reanudar:.0f} °C sin perder la respuesta."}
            esperado = gobernador.enfriar(motivo, cancelar, None, tramo=tramo)
            ahora = gobernador.monitor.gpu()
            yield {"t": "termico", "pausa": False,
                   "v": f"GPU a {ahora or 0:.0f} °C tras {esperado:.0f} s: se reanuda."}

        # «Detener» cierra las conexiones activas; durante una pausa térmica no hay ninguna,
        # así que el chat se apunta aquí para que también lo despierte
        if cancelar is None:
            cancelar = threading.Event()
        with self._streams_lock:
            self.__dict__.setdefault("_cancelables", set()).add(cancelar)
        monitor = gobernador.monitor.trabajando() if gobernador is not None else None
        if monitor is not None:
            monitor.__enter__()
        try:
            if gobernador is not None:
                tramo = None
                yield from enfriar("antes_de_paso")
            for ronda in range(max_rondas):
                contenido, pensamiento, llamadas, probabilidades = "", "", [], []
                estadisticas = None
                while True:
                    previo = []
                    if contenido or pensamiento:
                        asistente_parcial: Dict[str, Any] = {"role": "assistant", "content": contenido}
                        if pensamiento:
                            asistente_parcial["thinking"] = pensamiento
                        previo = [asistente_parcial]
                    payload: Dict[str, Any] = {"model": model, "messages": msgs + previo, "stream": True,
                                               "options": opciones, **base}
                    if definiciones:
                        payload["tools"] = definiciones
                    if logprobs:
                        payload["logprobs"] = True
                        payload["top_logprobs"] = int(logprobs)
                    tramo = gobernador.empezar_tramo() if gobernador is not None else None
                    motivo, terminado = None, False
                    ultimo_control = time.time()
                    res = None
                    try:
                        res = self._post_con_recuperacion(url, payload)
                        if res.status_code != 200:
                            yield {"t": "error", "v": f"Ollama {res.status_code}: {self._error_de(res)}"}
                            return
                        for linea in res.iter_lines():
                            if not linea:
                                continue
                            datos = json.loads(linea.decode("utf-8"))
                            if datos.get("error"):
                                yield {"t": "error", "v": str(datos["error"])}
                                return
                            msg = datos.get("message") or {}
                            if msg.get("thinking"):
                                pensamiento += msg["thinking"]
                                yield {"t": "pensando", "v": msg["thinking"]}
                            if msg.get("content"):
                                contenido += msg["content"]
                                yield {"t": "texto", "v": msg["content"]}
                            if msg.get("tool_calls"):
                                llamadas.extend(msg["tool_calls"])
                            if datos.get("logprobs"):
                                probabilidades.extend(datos["logprobs"])
                            if datos.get("done"):
                                estadisticas = self.metricas(datos, opciones.get("num_ctx"))
                                terminado = True
                                break
                            if cancelar is not None and cancelar.is_set():
                                yield {"t": "aviso", "v": "Detenido."}
                                return
                            ahora = time.time()
                            if gobernador is not None and ahora - ultimo_control >= 1.0:
                                ultimo_control = ahora
                                motivo = gobernador.debe_cortar(tramo)
                                # El modo suave no corta a mitad del razonamiento (el modelo lo daría por cerrado)
                                if motivo == "ritmo" and msg.get("thinking") and not msg.get("content"):
                                    motivo = None
                                if motivo:
                                    break
                    except Exception as e:
                        yield {"t": "error", "v": f"Error de conexión con Ollama: {e}"}
                        return
                    finally:
                        if res is not None:
                            with self._streams_lock:
                                self._active_streams.discard(res)
                            try:
                                res.close()
                            except Exception:
                                pass
                    if gobernador is not None and (terminado or not motivo):
                        gobernador.terminar_tramo(tramo, motivo)
                    if terminado or not motivo:
                        break
                    # Cortar la conexión detiene la generación en Ollama: es lo que enfría
                    if not contenido and pensamiento and motivo != "ritmo":
                        yield {"t": "aviso", "v": "Hubo una pausa térmica durante el razonamiento: al retomar, "
                                                  "el modelo lo cerró y pasó a responder."}
                    yield from enfriar(motivo)
                    gobernador.terminar_tramo(tramo, motivo)
                    if cancelar is not None and cancelar.is_set():
                        yield {"t": "aviso", "v": "Detenido."}
                        return

                if probabilidades:
                    yield {"t": "logprobs", "v": [
                        {"token": p.get("token"), "logprob": p.get("logprob"),
                         "alternativas": [{"token": a.get("token"), "logprob": a.get("logprob")}
                                          for a in (p.get("top_logprobs") or [])]}
                        for p in probabilidades[:4000]]}
                if not llamadas or herramientas is None:
                    if estadisticas:
                        yield {"t": "stats", "v": {**estadisticas, "rondas": ronda + 1}}
                    return

                asistente: Dict[str, Any] = {"role": "assistant", "content": contenido, "tool_calls": llamadas}
                if pensamiento:
                    asistente["thinking"] = pensamiento
                msgs.append(asistente)
                for llamada in llamadas:
                    funcion = llamada.get("function") or {}
                    nombre = funcion.get("name", "")
                    argumentos = funcion.get("arguments") or {}
                    yield {"t": "herramienta", "nombre": nombre, "argumentos": argumentos}
                    resultado = herramientas.ejecutar(nombre, argumentos)
                    yield {"t": "resultado", "nombre": nombre, "v": resultado[:2000]}
                    msgs.append({"role": "tool", "tool_name": nombre, "content": resultado})
            yield {"t": "aviso", "v": f"Se alcanzó el máximo de {max_rondas} rondas de herramientas."}
        finally:
            with self._streams_lock:
                self._cancelables.discard(cancelar)
            if monitor is not None:
                monitor.__exit__(None, None, None)

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
        """ `think` controla el razonamiento en voz alta de los modelos que lo traen.

        Qwen3 lo lleva conmutable, y la diferencia importa: en un paso que debe
        devolver JSON, el bloque de pensamiento ensucia la salida y se come la
        ventana; en uno que debe criticar, es justamente lo que aporta. Se pasa
        None para modelos que no lo soportan, porque enviarles el campo no les
        afecta pero tampoco hace falta.
        """
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": True,
            "options": self._build_options(options, model, uso)
        }
        if options and options.get("format"):
            payload["format"] = options.get("format")
        if think is None and on_thinking is not None and "thinking" in self.capacidades(model):
            think = True
        sistema = self._completar_payload(payload, model, uso, think, system_prompt)["sistema"]
        if sistema:
            payload["system"] = sistema

        # Con el gobernador térmico (modo suave y límite de temperatura) la respuesta se
        # genera por tramos: se pausa y se sigue donde quedó por /api/chat, con lo ya escrito
        # como inicio del asistente (medido: el resultado es idéntico al de una sola vez y
        # retomar relee lo escrito en milisegundos). Sin gobernador, una sola petición.
        gobernador = getattr(self, "gobernador", None)
        tope = int(payload["options"].get("num_predict") or 0)
        respuesta, pensamiento, generados = "", "", 0
        in_think_tag = False
        cancelar = threading.Event()
        with self._streams_lock:
            self.__dict__.setdefault("_cancelables", set()).add(cancelar)
        monitor = gobernador.monitor.trabajando() if gobernador is not None else None
        if monitor is not None:
            monitor.__enter__()
        res = None
        try:
            primera = True
            while True:
                if primera:
                    res = self._post_con_recuperacion(url, payload)
                else:
                    mensajes = ([{"role": "system", "content": sistema}] if sistema else []) + [{"role": "user", "content": prompt}]
                    asistente: Dict[str, Any] = {"role": "assistant", "content": respuesta}
                    if pensamiento:
                        asistente["thinking"] = pensamiento
                    seguir = {k: v for k, v in payload.items() if k not in ("prompt", "system", "raw", "context")}
                    seguir["options"] = dict(payload["options"])
                    if tope > 0:
                        seguir["options"]["num_predict"] = max(1, tope - generados)
                    seguir["messages"] = mensajes + [asistente]
                    res = self._post_con_recuperacion(f"{self.base_url}/api/chat", seguir)
                if res.status_code != 200:
                    detalle = self._error_de(res)
                    yield f"[Error Ollama: {res.status_code}{': ' + detalle if detalle else ''}]"
                    return
                tramo = gobernador.empezar_tramo() if gobernador is not None else None
                ultimo_control = time.time()
                motivo, terminado, pensando_ahora = None, False, False
                for line in res.iter_lines():
                    if not line:
                        continue
                    data = json.loads(line.decode('utf-8'))
                    mensaje = data.get("message") or {}
                    thinking_part = data.get("thinking") or mensaje.get("thinking") or ""
                    if thinking_part:
                        pensamiento += thinking_part
                        generados += 1
                        pensando_ahora = True
                        if on_thinking:
                            on_thinking(thinking_part)

                    response_part = data.get("response") or mensaje.get("content") or ""
                    if response_part:
                        respuesta += response_part
                        generados += 1
                        pensando_ahora = False
                        if "<think>" in response_part:
                            in_think_tag = True
                        if in_think_tag:
                            clean_think = response_part.replace("<think>", "").replace("</think>", "")
                            if clean_think and on_thinking:
                                on_thinking(clean_think)
                            if "</think>" in response_part:
                                in_think_tag = False
                        else:
                            if on_token:
                                on_token(response_part)
                        yield response_part
                    if data.get("done", False):
                        terminado = True
                        if on_stats is not None:
                            on_stats(self.metricas(data, payload["options"].get("num_ctx")))
                        break
                    ahora = time.time()
                    if gobernador is not None and ahora - ultimo_control >= 1.0:
                        ultimo_control = ahora
                        motivo = gobernador.debe_cortar(tramo)
                        # Cortar a mitad del razonamiento hace que el modelo lo dé por cerrado:
                        # el modo suave espera a que empiece a responder (el límite, no)
                        if motivo == "ritmo" and (pensando_ahora or in_think_tag):
                            motivo = None
                        if motivo:
                            break
                with self._streams_lock:
                    self._active_streams.discard(res)
                try:
                    res.close()
                except Exception:
                    pass
                if terminado or not motivo or cancelar.is_set() or (tope > 0 and generados >= tope):
                    if gobernador is not None and tramo is not None:
                        gobernador.terminar_tramo(tramo, None if terminado else motivo)
                    break
                gobernador.enfriar(motivo, cancelar, None, tramo=tramo)
                gobernador.terminar_tramo(tramo, motivo)
                if cancelar.is_set():
                    break
                primera = False
        except Exception as e:
            yield f"[Error de conexión con Ollama: {str(e)}]"
        finally:
            with self._streams_lock:
                self.__dict__.setdefault("_cancelables", set()).discard(cancelar)
            if res is not None:
                with self._streams_lock:
                    self._active_streams.discard(res)
                try:
                    res.close()
                except Exception:
                    pass
            if monitor is not None:
                monitor.__exit__(None, None, None)

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
        """ Libera la memoria VRAM descargando los modelos que Prig tiene cargados.

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
        if self._ollama_proc and self._ollama_proc.poll() is None:
            try:
                self._ollama_proc.terminate()
                self._ollama_proc.wait(timeout=2)
            except Exception:
                try:
                    self._ollama_proc.kill()
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

    def explain_seguimiento_block(self, goal: str, block: dict, model: str = "qwen2.5-coder:7b", use_web: bool = True):
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
        prompt = f"Meta del Alumno: {goal}\n\nBloque a Explicar:\n- Título: {block.get('title')}\n- Temas: {', '.join(block.get('topics', []))}\n- Objetivo: {block.get('learning_objective')}\n- Validación: {block.get('validation_check')}\n\n{web_context}\n¡Por favor, dame la clase!"
        
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


