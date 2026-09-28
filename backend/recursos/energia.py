"""
Energía de la CPU con permisos de root (opcional): turbo apagado, CPU en ahorro y tope de
potencia sostenida. Complementa al modo frío (recursos/frio.py): cada token cuesta menos calor,
así que a la misma temperatura el modelo va más rápido.

El trabajo de root lo hace SOLO el ayudante `prig-energia` (recursos/nativo/), instalado una vez
como root en /usr/local/libexec/ con su política de polkit. Cada uso pasa por pkexec, que pide la
contraseña de administrador (y la recuerda unos minutos): Prig nunca guarda contraseñas ni corre
como root.

Leer el estado no necesita permisos: todo sale de /sys.

Pruebas: PRIG_ENERGIA_AYUDANTE (el script a ejecutar), PRIG_ENERGIA_SIN_PKEXEC=1 (ejecutarlo
directamente, como usuario) y PRIG_ENERGIA_RAIZ (un /sys falso).
"""

import hashlib
import json
import os
import shutil
import subprocess
from typing import Any, Dict, Optional

NATIVO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nativo")
FUENTE_AYUDANTE = os.path.join(NATIVO, "prig-energia")
FUENTE_POLITICA = os.path.join(NATIVO, "org.prig.energia.policy")
AYUDANTE = "/usr/local/libexec/prig-energia"
POLITICA = "/usr/share/polkit-1/actions/org.prig.energia.policy"
VATIOS_POR_DEFECTO = 20


class ErrorEnergia(Exception):
    pass


def _raiz() -> str:
    return os.environ.get("PRIG_ENERGIA_RAIZ", "")


def _ayudante() -> str:
    return os.environ.get("PRIG_ENERGIA_AYUDANTE") or AYUDANTE


def _leer(ruta: str) -> Optional[str]:
    try:
        with open(_raiz() + ruta) as f:
            return f.read().strip()
    except OSError:
        return None


def _sha(ruta: str) -> Optional[str]:
    try:
        with open(ruta, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def instalacion() -> Dict[str, Any]:
    """ ¿Está el ayudante instalado, es de root y es la versión de este Prig? """
    if os.environ.get("PRIG_ENERGIA_AYUDANTE"):
        return {"instalado": True, "al_dia": True, "seguro": True}
    try:
        st = os.stat(AYUDANTE)
    except OSError:
        return {"instalado": False, "al_dia": False, "seguro": False, "pkexec": bool(shutil.which("pkexec"))}
    # Solo es seguro si nadie más que root puede cambiarlo
    seguro = st.st_uid == 0 and not (st.st_mode & 0o022)
    return {"instalado": os.path.isfile(POLITICA), "al_dia": _sha(AYUDANTE) == _sha(FUENTE_AYUDANTE) and _sha(POLITICA) == _sha(FUENTE_POLITICA),
            "seguro": seguro, "pkexec": bool(shutil.which("pkexec"))}


def estado() -> Dict[str, Any]:
    """ Turbo, gobernador, preferencia de energía y tope de potencia, sin permisos """
    no_turbo = _leer("/sys/devices/system/cpu/intel_pstate/no_turbo")
    boost = _leer("/sys/devices/system/cpu/cpufreq/boost")
    turbo = (no_turbo == "0") if no_turbo is not None else ((boost == "1") if boost is not None else None)
    pl1 = _leer("/sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw")
    modo = _leer("/run/prig-energia/modo") or "normal"
    return {
        "turbo": turbo,
        "gobernador": _leer("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"),
        "preferencia": _leer("/sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference"),
        "pl1_w": int(pl1) // 1_000_000 if pl1 and pl1.isdigit() else None,
        "modo": modo,
        "auto_cpufreq": any(os.path.exists(_raiz() + p) for p in ("/snap/bin/auto-cpufreq", "/usr/local/bin/auto-cpufreq", "/usr/bin/auto-cpufreq")),
        **instalacion(),
    }


def _pkexec(args, timeout: int = 120) -> subprocess.CompletedProcess:
    if os.environ.get("PRIG_ENERGIA_SIN_PKEXEC") == "1":
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if not shutil.which("pkexec"):
        raise ErrorEnergia("Falta pkexec (polkit): no se puede pedir permiso de administrador.")
    r = subprocess.run(["pkexec", *args], capture_output=True, text=True, timeout=timeout)
    if r.returncode == 126:
        raise ErrorEnergia("Cancelaste la contraseña: no se cambió nada.")
    if r.returncode == 127:
        raise ErrorEnergia("El sistema no dio permiso de administrador.")
    return r


def instalar() -> Dict[str, Any]:
    """ Copia el ayudante y su política como root (pide la contraseña una vez) """
    orden = ('install -D -o root -g root -m 0755 "$1" "$2" && '
             'install -D -o root -g root -m 0644 "$3" "$4"')
    r = _pkexec(["/bin/sh", "-c", orden, "prig-energia", FUENTE_AYUDANTE, AYUDANTE, FUENTE_POLITICA, POLITICA])
    if r.returncode != 0:
        raise ErrorEnergia(f"No se pudo instalar el ayudante: {(r.stderr or r.stdout).strip()[:300]}")
    return estado()


def _ejecutar(*args) -> Dict[str, Any]:
    inst = instalacion()
    if not inst["instalado"]:
        raise ErrorEnergia("Primero instala el ayudante de energía (pide la contraseña una vez).")
    if not inst["seguro"]:
        raise ErrorEnergia(f"{AYUDANTE} no es solo de root: por seguridad no se usa. Reinstálalo.")
    r = _pkexec([_ayudante(), *args])
    try:
        datos = json.loads((r.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise ErrorEnergia(f"El ayudante no respondió bien: {(r.stderr or r.stdout).strip()[:300]}")
    if not datos.get("ok"):
        raise ErrorEnergia(datos.get("error") or "El ayudante rechazó la orden.")
    return datos


def frio(vatios: int = VATIOS_POR_DEFECTO) -> Dict[str, Any]:
    """ Turbo apagado, CPU en ahorro y tope de potencia en `vatios` """
    if not isinstance(vatios, int) or not 10 <= vatios <= 65:
        raise ErrorEnergia("El tope de potencia debe estar entre 10 y 65 W.")
    _ejecutar("frio", str(vatios))
    return estado()


def normal() -> Dict[str, Any]:
    """ Lo que había antes de «frio» """
    _ejecutar("normal")
    return estado()
