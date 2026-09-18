"""
Radiografía de la máquina: lo que decide qué modelo cabe y a qué velocidad va.

Solo lee, nunca cambia nada, y tarda en torno a un segundo. Lo que mide, y por qué
cada cosa importa:

  · VRAM LIBRE DE VERDAD, no la total. En un portátil con gráficos híbridos el
    escritorio va por la integrada y la dedicada queda casi entera (medido: 15 MiB
    usados en reposo en una RTX 4050); en un sobremesa el escritorio se lleva entre
    300 y 800 MB, que es justo lo que separa "cabe" de "no cabe".
  · NÚCLEOS FÍSICOS, no hilos. La parte del modelo que corre en CPU rinde peor si
    se reparte entre hilos de hyperthreading.
  · RAM DISPONIBLE y SWAP. Un modelo que empieza a paginar a disco no va lento: se
    para. Hay que verlo venir.
  · QUIÉN ARRANCÓ OLLAMA. Las variables del servidor solo se pueden cambiar si el
    proceso es de Prig; si lo gestiona systemd, hay que decírselo al usuario.
  · ALIMENTACIÓN. Con batería no se lanza una extracción de una noche sin avisar.
"""

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import time
import urllib.request
from typing import Any, Dict, List, Optional

OLLAMA = os.environ.get("PRIG_OLLAMA_URL", "http://localhost:11434")


def _ejecutar(cmd: List[str], timeout: int = 5) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


# ===========================================================================
# GPU
# ===========================================================================

def gpus_nvidia() -> List[Dict[str, Any]]:
    if not shutil.which("nvidia-smi"):
        return []
    campos = ("index,name,memory.total,memory.used,memory.free,temperature.gpu,"
              "power.draw,power.limit,driver_version,compute_cap,utilization.gpu")
    salida = _ejecutar(["nvidia-smi", f"--query-gpu={campos}",
                        "--format=csv,noheader,nounits"])
    cuda = re.search(r"CUDA Version:\s*([\d.]+)", _ejecutar(["nvidia-smi"]))
    gpus = []
    for linea in salida.strip().splitlines():
        p = [x.strip() for x in linea.split(",")]
        if len(p) < 11:
            continue

        def num(x):
            try:
                return float(x)
            except ValueError:
                return None
        gpus.append({
            "fabricante": "nvidia", "indice": int(p[0]), "nombre": p[1],
            "vram_total_mb": num(p[2]), "vram_usada_mb": num(p[3]),
            "vram_libre_mb": num(p[4]), "temperatura_c": num(p[5]),
            "consumo_w": num(p[6]), "limite_w": num(p[7]),
            "driver": p[8], "compute_cap": p[9], "uso_pct": num(p[10]),
            "cuda": cuda.group(1) if cuda else None,
            # Ada (8.9) y Ampere (8.x) tienen FlashAttention; Turing (7.5), no
            "flash_attention": _cc_ge(p[9], "8.0"),
            "bf16": _cc_ge(p[9], "8.0"),
        })
    procesos = _ejecutar(["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory",
                          "--format=csv,noheader,nounits"])
    ajenos = []
    for linea in procesos.strip().splitlines():
        p = [x.strip() for x in linea.split(",")]
        if len(p) >= 3 and "ollama" not in p[1].lower():
            try:
                ajenos.append({"pid": int(p[0]), "proceso": os.path.basename(p[1]),
                               "mb": float(p[2])})
            except ValueError:
                pass
    for g in gpus:
        g["otros_procesos"] = ajenos
    return gpus


def _cc_ge(cc: str, minimo: str) -> bool:
    try:
        return tuple(int(x) for x in cc.split(".")) >= tuple(int(x) for x in minimo.split("."))
    except ValueError:
        return False


def gpus_amd() -> List[Dict[str, Any]]:
    if not shutil.which("rocm-smi"):
        return []
    try:
        datos = json.loads(_ejecutar(["rocm-smi", "--showmeminfo", "vram",
                                      "--showproductname", "--json"]) or "{}")
    except json.JSONDecodeError:
        return []
    gpus = []
    for i, (clave, v) in enumerate(sorted(datos.items())):
        if not clave.startswith("card"):
            continue
        total = int(v.get("VRAM Total Memory (B)", 0)) / 1024 / 1024
        usada = int(v.get("VRAM Total Used Memory (B)", 0)) / 1024 / 1024
        gpus.append({"fabricante": "amd", "indice": i,
                     "nombre": v.get("Card series") or v.get("Card model") or clave,
                     "vram_total_mb": total, "vram_usada_mb": usada,
                     "vram_libre_mb": total - usada, "temperatura_c": None,
                     "driver": "rocm", "flash_attention": False, "otros_procesos": []})
    return gpus


def gpu_apple(ram_bytes: int) -> List[Dict[str, Any]]:
    """ En Apple Silicon la GPU usa la misma memoria que la CPU.

    macOS deja a la GPU unas dos terceras partes de la RAM en equipos de hasta 36 GB
    y unas tres cuartas partes por encima. No es una VRAM aparte: lo que usa el
    modelo sale de la misma RAM que el resto del sistema.
    """
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        return []
    fraccion = 0.75 if ram_bytes > 36 * 1024 ** 3 else 0.66
    total = ram_bytes / 1024 / 1024 * fraccion
    nombre = _ejecutar(["sysctl", "-n", "machdep.cpu.brand_string"]).strip() or "Apple Silicon"
    return [{"fabricante": "apple", "indice": 0, "nombre": nombre,
             "vram_total_mb": total, "vram_usada_mb": 0, "vram_libre_mb": total,
             "memoria_unificada": True, "flash_attention": True, "otros_procesos": []}]


# ===========================================================================
# CPU, memoria, disco, energía
# ===========================================================================

def cpu() -> Dict[str, Any]:
    fisicos = logicos = None
    try:
        import psutil
        fisicos = psutil.cpu_count(logical=False)
        logicos = psutil.cpu_count(logical=True)
    except Exception:
        logicos = os.cpu_count()
    modelo, banderas = platform.processor() or "", set()
    if os.path.exists("/proc/cpuinfo"):
        with open("/proc/cpuinfo", encoding="utf-8", errors="ignore") as f:
            texto = f.read()
        m = re.search(r"model name\s*:\s*(.+)", texto)
        modelo = m.group(1).strip() if m else modelo
        m = re.search(r"flags\s*:\s*(.+)", texto)
        banderas = set(m.group(1).split()) if m else set()
        if not fisicos:
            nucleos = set(re.findall(r"core id\s*:\s*(\d+)", texto))
            fisicos = len(nucleos) or logicos
    elif platform.system() == "Darwin":
        modelo = _ejecutar(["sysctl", "-n", "machdep.cpu.brand_string"]).strip() or modelo
    return {
        "modelo": modelo, "nucleos_fisicos": fisicos or logicos or 1,
        "hilos": logicos or 1,
        "avx2": "avx2" in banderas, "avx512": "avx512f" in banderas,
        "amx": "amx_tile" in banderas,
        "arquitectura": platform.machine(),
    }


def memoria() -> Dict[str, Any]:
    try:
        import psutil
        vm, sw = psutil.virtual_memory(), psutil.swap_memory()
        return {"ram_total": vm.total, "ram_disponible": vm.available,
                "swap_total": sw.total, "swap_usada": sw.used}
    except Exception:
        pass
    datos = {}
    if os.path.exists("/proc/meminfo"):
        with open("/proc/meminfo") as f:
            for linea in f:
                k, _, v = linea.partition(":")
                datos[k] = int(v.split()[0]) * 1024
    return {"ram_total": datos.get("MemTotal", 0),
            "ram_disponible": datos.get("MemAvailable", 0),
            "swap_total": datos.get("SwapTotal", 0),
            "swap_usada": datos.get("SwapTotal", 0) - datos.get("SwapFree", 0)}


def ancho_banda_ram(mb: int = 256) -> float:
    """ Velocidad de copia de memoria, en GB/s. Tarda unos 200 ms.

    En la parte del modelo que corre en CPU, los tokens por segundo los limita la
    velocidad a la que se leen los pesos de la RAM, no los núcleos. Esta medida en
    Python puro subestima el ancho de banda real; se usa solo como valor previo y la
    calibración con un modelo de verdad la sustituye. En la máquina de referencia
    (RTX 4050, 62 GB) dio el factor que traduce esta medida a lo que rinde Ollama.
    """
    bloque = bytearray(os.urandom(1024 * 1024)) * mb
    destino = bytearray(len(bloque))
    t0 = time.perf_counter()
    for _ in range(3):
        destino[:] = bloque
    dt = time.perf_counter() - t0
    return round(len(bloque) * 3 / dt / 1e9, 2)


def disco(ruta: Optional[str] = None) -> Dict[str, Any]:
    ruta = ruta or os.environ.get("OLLAMA_MODELS") or os.path.expanduser("~/.ollama/models")
    base = ruta
    while base and not os.path.exists(base):
        base = os.path.dirname(base)
    try:
        uso = shutil.disk_usage(base or "/")
        return {"ruta_modelos": ruta, "libre": uso.free, "total": uso.total}
    except Exception:
        return {"ruta_modelos": ruta, "libre": 0, "total": 0}


def energia() -> Dict[str, Any]:
    """ ¿Portátil? ¿Con batería? Sin batería no hay por qué frenar nada. """
    info = {"portatil": False, "con_bateria": None, "bateria_pct": None}
    try:
        import psutil
        b = psutil.sensors_battery()
        if b is not None:
            info.update(portatil=True, con_bateria=not b.power_plugged,
                        bateria_pct=round(b.percent))
            return info
    except Exception:
        pass
    # El tipo de chasis es lo fiable: hay portátiles que no exponen la batería en
    # /sys, y sin esto se tratarían como sobremesa (sin gobernador térmico ni aviso
    # de batería). 8-10 y 14 son portátil, notebook, subnotebook.
    if _leer("/sys/class/dmi/id/chassis_type") in ("8", "9", "10", "14", "31", "32"):
        info["portatil"] = True
    base = "/sys/class/power_supply"
    if os.path.isdir(base):
        for n in os.listdir(base):
            if n.startswith("BAT"):
                info["portatil"] = True
            tipo = _leer(os.path.join(base, n, "type"))
            if tipo == "Mains":
                enchufado = _leer(os.path.join(base, n, "online"))
                if enchufado in ("0", "1"):
                    info["con_bateria"] = enchufado == "0"
    return info


def _leer(ruta: str) -> str:
    try:
        with open(ruta) as f:
            return f.read().strip()
    except Exception:
        return ""


def sistema() -> Dict[str, Any]:
    wsl = "microsoft" in platform.release().lower()
    return {"so": platform.system(), "version": platform.release(),
            "distribucion": _distribucion(), "wsl": wsl,
            "python": platform.python_version()}


def _distribucion() -> str:
    texto = _leer("/etc/os-release")
    m = re.search(r'PRETTY_NAME="([^"]+)"', texto)
    return m.group(1) if m else platform.platform()


# ===========================================================================
# Ollama
# ===========================================================================

def ollama() -> Dict[str, Any]:
    info: Dict[str, Any] = {"responde": False, "version": None, "pid": None,
                            "binario": None, "dueno": None, "entorno": {},
                            "modelos_cargados": [], "ejecutores": []}
    try:
        with urllib.request.urlopen(OLLAMA + "/api/version", timeout=3) as r:
            info["version"] = json.load(r).get("version")
            info["responde"] = True
        with urllib.request.urlopen(OLLAMA + "/api/ps", timeout=3) as r:
            info["modelos_cargados"] = [
                {"nombre": m["name"], "gb": round(m.get("size", 0) / 1e9, 2),
                 "gb_vram": round(m.get("size_vram", 0) / 1e9, 2)}
                for m in json.load(r).get("models", [])]
    except Exception:
        pass

    pid = _pid_ollama()
    if pid:
        info["pid"] = pid
        try:
            info["binario"] = os.readlink(f"/proc/{pid}/exe")
        except Exception:
            pass
        try:
            with open(f"/proc/{pid}/environ", "rb") as f:
                pares = f.read().split(b"\0")
            info["entorno"] = {k: v for k, _, v in
                               (p.decode(errors="ignore").partition("=") for p in pares)
                               if k.startswith(("OLLAMA_", "LLAMA_ARG_"))}
        except Exception:
            pass
    info["dueno"] = _dueno(info)
    if info["binario"]:
        lib = os.path.join(os.path.dirname(info["binario"]), "lib", "ollama")
        if os.path.isdir(lib):
            info["ejecutores"] = sorted(d for d in os.listdir(lib)
                                        if os.path.isdir(os.path.join(lib, d)))
    return info


def _pid_ollama() -> Optional[int]:
    salida = _ejecutar(["pgrep", "-f", "ollama serve"])
    for linea in salida.split():
        try:
            pid = int(linea)
        except ValueError:
            continue
        if pid != os.getpid():
            return pid
    return None


def _dueno(info: Dict[str, Any]) -> Optional[str]:
    """ Quién gestiona el proceso: decide si Prig puede reiniciarlo con otras
    variables o si tiene que pedírselo al usuario. """
    if not info.get("responde"):
        return None
    for alcance in ([], ["--user"]):
        if _ejecutar(["systemctl", *alcance, "is-active", "ollama"]).strip() == "active":
            return "systemd" if not alcance else "systemd-usuario"
    binario = info.get("binario") or ""
    raiz_prig = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if binario.startswith(os.path.join(raiz_prig, "bin")):
        return "prig"
    return "usuario" if info.get("pid") else "desconocido"


# ===========================================================================
# Todo junto
# ===========================================================================

def radiografia(medir_ram: bool = True) -> Dict[str, Any]:
    mem = memoria()
    gpus = gpus_nvidia() or gpus_amd() or gpu_apple(mem.get("ram_total", 0))
    ener = energia()
    # Una GPU "Laptop" delata un portátil aunque la batería no se vea
    if any("laptop" in (g.get("nombre") or "").lower() for g in gpus):
        ener["portatil"] = True
    datos = {
        "tomada": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "sistema": sistema(),
        "cpu": cpu(),
        "memoria": mem,
        "gpus": gpus,
        "disco": disco(),
        "energia": ener,
        "ollama": ollama(),
        "ancho_banda_ram_gbps": ancho_banda_ram() if medir_ram else None,
    }
    datos["huella"] = huella(datos)
    return datos


def huella(datos: Dict[str, Any]) -> str:
    """ Identifica la combinación de hardware y software que afecta a las medidas.

    Si cambia (otra GPU, otro driver, otra versión de Ollama, otra RAM), lo que se
    calibró deja de valer y hay que volver a medir.
    """
    g = (datos.get("gpus") or [{}])[0]
    partes = [
        g.get("nombre", "sin-gpu"), str(round(g.get("vram_total_mb") or 0)),
        str(g.get("driver", "")), datos.get("cpu", {}).get("modelo", ""),
        str(round((datos.get("memoria", {}).get("ram_total") or 0) / 1024 ** 3)),
        str(datos.get("ollama", {}).get("version", "")),
    ]
    return hashlib.sha256("|".join(partes).encode()).hexdigest()[:16]
