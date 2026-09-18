"""
Ajustes del SERVIDOR de Ollama: los que no se pueden mandar en cada petición.

La caché KV cuantizada, las ranuras en paralelo o FlashAttention se fijan con
variables de entorno al arrancar `ollama serve`. Cambiarlas exige reiniciarlo, y
eso solo es seguro si el proceso es de Prig:

  · dueño "prig": Prig lo arrancó con su binario → se reinicia con las variables.
  · dueño "systemd" / "systemd-usuario": lo gestiona el sistema → se dan las
    instrucciones exactas (un override de systemd) y no se toca nada.
  · dueño "usuario": alguien lo lanzó a mano en una terminal → instrucciones.

Nunca se actualiza ni se sustituye el binario de Ollama del sistema.
"""

import os
import signal
import time
from typing import Any, Dict, Optional

from . import detector
from .almacen import almacen
from .calculadora import servidor_efectivo

# Variables que Prig gestiona. El resto (OLLAMA_MODELS, OLLAMA_HOST…) se respeta.
GESTIONADAS = ("OLLAMA_KV_CACHE_TYPE", "OLLAMA_NUM_PARALLEL", "OLLAMA_FLASH_ATTENTION",
               "OLLAMA_MAX_LOADED_MODELS", "OLLAMA_KEEP_ALIVE",
               # Verificadas una a una en un Ollama aparte (puerto 11500), midiendo el efecto
               "OLLAMA_CONTEXT_LENGTH", "OLLAMA_LLM_LIBRARY", "LLAMA_ARG_FIT_TARGET",
               "OLLAMA_LOAD_TIMEOUT", "OLLAMA_IGPU_ENABLE", "OLLAMA_MODELS", "OLLAMA_HOST",
               "OLLAMA_ORIGINS", "OLLAMA_DEBUG", "OLLAMA_NO_CLOUD")

VALORES_VALIDOS = {
    "OLLAMA_KV_CACHE_TYPE": {"f16", "q8_0", "q4_0"},
    "OLLAMA_FLASH_ATTENTION": {"0", "1"},
    "OLLAMA_IGPU_ENABLE": {"0", "1"},
    "OLLAMA_DEBUG": {"0", "1"},
    "OLLAMA_NO_CLOUD": {"0", "1"},
    # Solo el puerto de siempre: Prig y el gestor de recursos hablan con el 11434
    "OLLAMA_HOST": {"127.0.0.1:11434", "0.0.0.0:11434"},
}

# Qué hace cada una y cómo se comprobó, para la interfaz
DESCRIPCIONES = {
    "OLLAMA_CONTEXT_LENGTH": ("Contexto por defecto", "Tokens de contexto cuando la petición no dice nada.",
                              "Con 3072, el modelo se carga con 3072 en vez de 4096."),
    "OLLAMA_LLM_LIBRARY": ("Motor de cálculo", "Fuerza la biblioteca: CUDA 12, CUDA 13, Vulkan o CPU. Vacío = automático.",
                           "cuda_v12, cuda_v13 y vulkan cargan en GPU (140 tok/s con cuda_v13); cpu deja la VRAM en 0."),
    "LLAMA_ARG_FIT_TARGET": ("VRAM libre a reservar (MiB)", "Margen que el reparto automático deja libre en la GPU.",
                             "Con 2500 MiB el 7B pasa de 4,75 a 3,31 GB en GPU."),
    "OLLAMA_LOAD_TIMEOUT": ("Tiempo máximo de carga", "Cuánto puede tardar en cargar un modelo antes de darlo por fallido. Mínimo 10s.",
                            "Con un valor mínimo la carga falla con «timed out waiting for llama-server»."),
    "OLLAMA_IGPU_ENABLE": ("Usar la gráfica integrada", "Permite usar también la GPU integrada del procesador.",
                           "Los dispositivos detectados pasan de 1 a 2 (la Intel integrada)."),
    "OLLAMA_MODELS": ("Carpeta de modelos", "Dónde guarda Ollama los modelos (por ejemplo, otro disco).",
                      "Apuntando a una carpeta vacía, la lista de modelos queda vacía."),
    "OLLAMA_HOST": ("Acceso desde la red", "127.0.0.1: solo este equipo. 0.0.0.0: cualquier equipo de tu red puede usar tus modelos.",
                    "En 0.0.0.0 responde por la IP de la red local; en 127.0.0.1 la rechaza."),
    "OLLAMA_ORIGINS": ("Webs con permiso", "Orígenes (https://…) que pueden llamar a Ollama desde el navegador, separados por comas.",
                       "Sin permiso: 403. Con el origen en la lista: 200 y cabecera CORS."),
    "OLLAMA_DEBUG": ("Registro detallado", "Escribe información de depuración en el registro del servidor.",
                     "El registro pasa a incluir líneas level=DEBUG."),
    "OLLAMA_NO_CLOUD": ("Bloquear la nube", "Impide usar modelos remotos y la búsqueda web de ollama.com: todo queda en tu equipo.",
                        "Un modelo :cloud pasa de 401 a 403 «ollama cloud is disabled»."),
}

import re as _re
_DURACION = _re.compile(r"^(\d+)(ms|s|m|h)$")
_ORIGEN = _re.compile(r"^(\*|https?://[a-zA-Z0-9.\-*]+(:\d+)?|app://[^,\s]+|file://[^,\s]*)$")


def librerias_disponibles() -> list:
    """ Motores instalados junto al binario de Ollama de Prig, más la CPU """
    raiz = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "lib", "ollama")
    libs = sorted(d for d in os.listdir(raiz) if os.path.isdir(os.path.join(raiz, d))) if os.path.isdir(raiz) else []
    return libs + ["cpu"]


def validar(cambios: Dict[str, Any]) -> Dict[str, str]:
    limpio: Dict[str, str] = {}
    for k, v in cambios.items():
        if k not in GESTIONADAS:
            raise ValueError(f"{k} no es un ajuste que Prig gestione")
        if v is None or v == "":
            limpio[k] = ""          # quitarla: vuelve al valor por defecto
            continue
        v = str(v).strip()
        if k in VALORES_VALIDOS and v not in VALORES_VALIDOS[k]:
            raise ValueError(f"{k}={v} no es válido")
        if k in ("OLLAMA_NUM_PARALLEL", "OLLAMA_MAX_LOADED_MODELS"):
            if not v.isdigit() or not 1 <= int(v) <= 8:
                raise ValueError(f"{k} debe ser un entero entre 1 y 8")
        if k == "OLLAMA_CONTEXT_LENGTH" and (not v.isdigit() or not 512 <= int(v) <= 262144):
            raise ValueError("El contexto por defecto debe estar entre 512 y 262144")
        if k == "LLAMA_ARG_FIT_TARGET" and (not v.isdigit() or not 0 <= int(v) <= 65536):
            raise ValueError("La VRAM a reservar debe estar entre 0 y 65536 MiB")
        if k == "OLLAMA_LLM_LIBRARY" and v not in librerias_disponibles():
            raise ValueError(f"Motor desconocido: {v}. Hay: {', '.join(librerias_disponibles())}")
        if k == "OLLAMA_LOAD_TIMEOUT":
            m = _DURACION.match(v)
            factor = {"ms": 0.001, "s": 1, "m": 60, "h": 3600}
            if not m or int(m.group(1)) * factor[m.group(2)] < 10:
                raise ValueError("El tiempo de carga debe ser de al menos 10s (ej. 90s, 5m); "
                                 "medido: con valores mínimos ningún modelo llega a cargar")
        if k == "OLLAMA_MODELS":
            v = os.path.abspath(os.path.expanduser(v))
            if not os.path.isdir(v) or not os.access(v, os.W_OK):
                raise ValueError(f"La carpeta de modelos no existe o no se puede escribir: {v}")
        if k == "OLLAMA_ORIGINS":
            partes = [x.strip() for x in v.split(",") if x.strip()]
            malos = [x for x in partes if not _ORIGEN.match(x)]
            if malos or not partes:
                raise ValueError(f"Orígenes no válidos: {', '.join(malos) or v}")
            v = ",".join(partes)
        limpio[k] = v
    # La caché cuantizada solo funciona con FlashAttention: sin ella, Ollama la
    # ignora en silencio y el usuario cree tener un ajuste que no tiene.
    if limpio.get("OLLAMA_KV_CACHE_TYPE") in ("q8_0", "q4_0"):
        limpio["OLLAMA_FLASH_ATTENTION"] = "1"
    return limpio


def estado(info_ollama: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    info = info_ollama or detector.ollama()
    guardado = almacen().entorno_servidor()
    real = info.get("entorno") or {}
    # Lo que Prig quiere y el servidor todavía no tiene (falta reiniciar)
    pendiente = {k: v for k, v in guardado.items() if real.get(k, "") != v}
    dueno = info.get("dueno")
    return {
        "responde": info.get("responde"),
        "version": info.get("version"),
        "binario": info.get("binario"),
        "dueno": dueno,
        "entorno": {k: real.get(k) for k in GESTIONADAS if real.get(k) is not None},
        "efectivo": servidor_efectivo(real),
        "guardado": guardado,
        "pendiente": pendiente,
        "puede_reiniciar": dueno in ("prig", None),
        "descripciones": DESCRIPCIONES,
        "librerias": librerias_disponibles(),
        "registro": ruta_registro(),
        "modelos_cargados": info.get("modelos_cargados", []),
    }


def instrucciones(dueno: Optional[str], entorno: Dict[str, str]) -> str:
    lineas = [f'{k}={v}' for k, v in sorted(entorno.items()) if v != ""]
    if dueno in ("systemd", "systemd-usuario"):
        usuario = " --user" if dueno == "systemd-usuario" else ""
        sudo = "" if usuario else "sudo "
        cuerpo = "\n".join(f'Environment="{l}"' for l in lineas)
        return (f"Ollama lo gestiona systemd, así que Prig no lo reinicia por su cuenta.\n"
                f"1. {sudo}systemctl{usuario} edit ollama\n"
                f"2. Añade:\n[Service]\n{cuerpo}\n"
                f"3. {sudo}systemctl{usuario} restart ollama")
    exportar = " ".join(lineas)
    return ("Ollama se lanzó a mano. Ciérralo y vuelve a arrancarlo así:\n"
            f"{exportar} ollama serve")


def aplicar(cambios: Dict[str, Any], motor=None, reiniciar: bool = True,
            forzar: bool = False) -> Dict[str, Any]:
    """ Guarda las variables y, si el servidor es de Prig, lo reinicia con ellas """
    limpio = validar(cambios)
    guardado = almacen().entorno_servidor()
    guardado.update(limpio)
    guardado = {k: v for k, v in guardado.items() if v != ""}
    almacen().guardar_entorno_servidor(guardado)

    info = detector.ollama()
    dueno = info.get("dueno")
    if dueno not in ("prig", None):
        return {"aplicado": False, "guardado": guardado, "dueno": dueno,
                "instrucciones": instrucciones(dueno, guardado)}
    if not reiniciar:
        return {"aplicado": False, "guardado": guardado, "dueno": dueno,
                "mensaje": "Guardado. Se usará la próxima vez que Prig arranque Ollama."}
    if info.get("modelos_cargados") and not forzar:
        return {"aplicado": False, "guardado": guardado, "dueno": dueno,
                "necesita_confirmar": True,
                "mensaje": "Hay modelos cargados: reiniciar corta lo que estén generando. "
                           "Confirma para reiniciar igualmente."}
    return reiniciar_servidor(info, motor, guardado)


def ruta_registro() -> str:
    return os.path.expanduser("~/.prig_ollama.log")


def abrir_registro():
    """ Archivo donde Prig manda la salida de su `ollama serve`. Antes iba a /dev/null
    y cualquier fallo llegaba sin explicación. Se rota al pasar de 5 MB. """
    ruta = ruta_registro()
    try:
        if os.path.exists(ruta) and os.path.getsize(ruta) > 5 * 1024 * 1024:
            os.replace(ruta, ruta + ".1")
        return open(ruta, "a", buffering=1, encoding="utf-8", errors="replace")
    except OSError:
        return None


def leer_registro(lineas: int = 400, dueno: Optional[str] = None) -> Dict[str, Any]:
    lineas = max(20, min(int(lineas), 5000))
    if dueno in ("systemd", "systemd-usuario"):
        import subprocess
        cmd = ["journalctl", *(["--user"] if dueno == "systemd-usuario" else []), "-u", "ollama", "-n", str(lineas), "--no-pager"]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and r.stdout.strip():
                return {"origen": "journalctl", "texto": r.stdout}
            return {"origen": "journalctl", "texto": "", "aviso": r.stderr.strip() or "Sin permiso para leer el registro del servicio"}
        except Exception as e:
            return {"origen": "journalctl", "texto": "", "aviso": str(e)}
    ruta = ruta_registro()
    if not os.path.exists(ruta):
        return {"origen": ruta, "texto": "", "aviso": "Todavía no hay registro: se crea cuando Prig arranca Ollama."}
    with open(ruta, "rb") as f:
        f.seek(0, 2)
        tam = f.tell()
        f.seek(max(0, tam - 400 * lineas))
        texto = f.read().decode("utf-8", errors="replace")
    return {"origen": ruta, "texto": "\n".join(texto.splitlines()[-lineas:])}


def entorno_arranque(base: Dict[str, str]) -> Dict[str, str]:
    """ El entorno con el que Prig arranca `ollama serve` """
    env = dict(base)
    for k, v in almacen().entorno_servidor().items():
        if k in GESTIONADAS and v != "":
            env[k] = v
    return env


def reiniciar_servidor(info: Dict[str, Any], motor, guardado: Dict[str, str]) -> Dict[str, Any]:
    pid = info.get("pid")
    if pid and info.get("dueno") == "prig":
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        for _ in range(40):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.25)
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            time.sleep(1)

    arrancado = False
    if motor is not None:
        try:
            arrancado = bool(motor.try_autostart_ollama())
        except Exception as e:
            return {"aplicado": False, "guardado": guardado, "error": str(e)}

    nuevo = detector.ollama()
    real = nuevo.get("entorno") or {}
    faltan = {k: v for k, v in guardado.items() if real.get(k) != v}
    almacen().evento("servidor_reiniciado",
                     "Ollama reiniciado con las variables de Prig." if not faltan
                     else "Ollama reiniciado, pero no tomó todas las variables.",
                     {"entorno": real, "faltan": faltan})
    return {"aplicado": arrancado and not faltan, "guardado": guardado,
            "dueno": nuevo.get("dueno"), "entorno": real, "faltan": faltan,
            "version": nuevo.get("version")}
