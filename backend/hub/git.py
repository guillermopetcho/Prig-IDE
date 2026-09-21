"""
git para Prig Hub: crear repositorios propios, seguir los de otros y publicar.

Seguridad:
  · solo se clona por HTTPS (y por file:// en las pruebas, con PRIG_HUB_GIT_LOCAL=1); los
    transportes ext:: y file quedan prohibidos, y una URL que empieza por «-» se rechaza;
  · git nunca pregunta por la terminal (GIT_TERMINAL_PROMPT=0) ni usa ganchos del repo;
  · el token de GitHub va solo en el entorno del proceso que empuja (GIT_CONFIG_*), nunca
    en la línea de comandos (visible en ps) ni en .git/config;
  · un repositorio de más de MAX_MB se descarta: Prig Hub es texto.
"""

import base64
import io
import os
import shutil
import subprocess
import tarfile
import tempfile
from typing import Dict, List, Optional

MAX_MB = 30
TIEMPO = 120


class ErrorGit(Exception):
    pass


def disponible() -> bool:
    return shutil.which("git") is not None


def _entorno(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    e = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    e.update({"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "", "SSH_ASKPASS": "", "LC_ALL": "C",
              "GIT_CONFIG_NOSYSTEM": "1"})
    e.update(extra or {})
    return e


def _protocolos() -> List[str]:
    local = os.environ.get("PRIG_HUB_GIT_LOCAL") == "1"
    return ["-c", "protocol.ext.allow=never", "-c", f"protocol.file.allow={'always' if local else 'never'}",
            "-c", "core.hooksPath=/dev/null", "-c", "advice.detachedHead=false"]


def correr(args: List[str], cwd: Optional[str] = None, extra: Optional[Dict[str, str]] = None,
           tiempo: int = TIEMPO, binario: bool = False):
    if not disponible():
        raise ErrorGit("git no está instalado (sudo apt install git).")
    try:
        r = subprocess.run(["git", *_protocolos(), *args], cwd=cwd, env=_entorno(extra), capture_output=True,
                           timeout=tiempo, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise ErrorGit("git tardó demasiado (¿sin conexión?).")
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", "replace").strip().splitlines()
        raise ErrorGit(_explicar(err[-1] if err else f"git {args[0]} falló"))
    return r.stdout if binario else r.stdout.decode("utf-8", "replace")


def _explicar(linea: str) -> str:
    bajo = linea.lower()
    if "could not resolve host" in bajo or "unable to access" in bajo and "resolve" in bajo:
        return "Sin conexión: no se pudo llegar al servidor."
    if "repository not found" in bajo or "not found" in bajo and "repository" in bajo:
        return "Ese repositorio no existe o es privado."
    if "authentication failed" in bajo or "could not read username" in bajo or "403" in bajo:
        return "El servidor rechazó el acceso: revisa el token de GitHub (necesita permiso de escritura en el repositorio)."
    if "non-fast-forward" in bajo or "fetch first" in bajo or "rejected" in bajo:
        return "El repositorio en GitHub tiene cambios que no están aquí. Trae esos cambios antes de publicar."
    return linea[:300]


def validar_url(url: str) -> str:
    u = (url or "").strip()
    if u.startswith("-") or any(c in u for c in " \n\t\\"):
        raise ErrorGit("Enlace de repositorio no válido.")
    if u.startswith("https://"):
        return u
    if os.environ.get("PRIG_HUB_GIT_LOCAL") == "1" and (u.startswith("file://") or os.path.isabs(u)):
        return u
    raise ErrorGit("Solo se pueden seguir repositorios por HTTPS (GitHub, GitLab, Codeberg…).")


def autor(nombre: str, correo: str) -> Dict[str, str]:
    return {"GIT_AUTHOR_NAME": nombre, "GIT_AUTHOR_EMAIL": correo,
            "GIT_COMMITTER_NAME": nombre, "GIT_COMMITTER_EMAIL": correo}


def auth_github(token: Optional[str]) -> Dict[str, str]:
    """ El token como cabecera HTTP, solo para este proceso y solo hacia github.com """
    if not token:
        return {}
    basico = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
            "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basico}"}


# ============================================================================ repositorios propios

def iniciar(carpeta: str):
    if not os.path.isdir(os.path.join(carpeta, ".git")):
        correr(["init", "-q", "-b", "main"], cwd=carpeta)


def guardar(carpeta: str, mensaje: str, firma: Dict[str, str]) -> Optional[str]:
    """ Commit de todo lo que cambió; None si no había nada que guardar """
    correr(["add", "-A"], cwd=carpeta)
    if not correr(["status", "--porcelain"], cwd=carpeta).strip():
        return None
    correr(["commit", "-q", "--no-gpg-sign", "-m", mensaje], cwd=carpeta, extra=firma)
    return cabeza(carpeta)


def cabeza(carpeta: str) -> Optional[str]:
    try:
        return correr(["rev-parse", "HEAD"], cwd=carpeta).strip()
    except ErrorGit:
        return None


def historial(carpeta: str, n: int = 20) -> List[Dict[str, str]]:
    try:
        salida = correr(["log", f"-{n}", "--format=%H%x1f%cI%x1f%s"], cwd=carpeta)
    except ErrorGit:
        return []
    filas = []
    for linea in salida.splitlines():
        partes = linea.split("\x1f")
        if len(partes) == 3:
            filas.append({"commit": partes[0], "fecha": partes[1], "mensaje": partes[2]})
    return filas


def fijar_remoto(carpeta: str, url: str):
    try:
        correr(["remote", "set-url", "origin", url], cwd=carpeta)
    except ErrorGit:
        correr(["remote", "add", "origin", url], cwd=carpeta)


def remoto(carpeta: str) -> Optional[str]:
    try:
        return correr(["remote", "get-url", "origin"], cwd=carpeta).strip() or None
    except ErrorGit:
        return None


def publicar(carpeta: str, token: Optional[str] = None):
    correr(["push", "-q", "origin", "HEAD:refs/heads/main"], cwd=carpeta, extra=auth_github(token), tiempo=180)


# ============================================================================ repositorios de otros

def _tamano_mb(carpeta: str) -> float:
    total = 0
    for raiz, _, archivos in os.walk(carpeta):
        for a in archivos:
            try:
                total += os.path.getsize(os.path.join(raiz, a))
            except OSError:
                pass
    return total / 1e6


def clonar(url: str, destino: str) -> str:
    """ Clon superficial en una carpeta temporal y, si es válido, se mueve a `destino` """
    url = validar_url(url)
    padre = os.path.dirname(destino)
    os.makedirs(padre, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix=".clon_", dir=padre)
    try:
        correr(["clone", "-q", "--depth", "1", "--no-tags", "--", url, tmp], tiempo=180)
        mb = _tamano_mb(tmp)
        if mb > MAX_MB:
            raise ErrorGit(f"El repositorio pesa {mb:.0f} MB: un repositorio de Prig Hub es texto (máximo {MAX_MB} MB).")
        if os.path.exists(destino):
            shutil.rmtree(destino)
        os.replace(tmp, destino)
        return cabeza(destino)
    finally:
        if os.path.exists(tmp):
            shutil.rmtree(tmp, ignore_errors=True)


def traer(carpeta: str) -> str:
    """ Descarga lo último del remoto SIN aplicarlo; devuelve el commit traído """
    correr(["fetch", "-q", "--depth", "1", "--no-tags", "origin", "HEAD"], cwd=carpeta, tiempo=180)
    return correr(["rev-parse", "FETCH_HEAD"], cwd=carpeta).strip()


def extraer(carpeta: str, commit: str) -> str:
    """ El contenido de un commit en una carpeta temporal (para leerlo y compararlo sin aplicarlo) """
    datos = correr(["archive", "--format=tar", commit], cwd=carpeta, binario=True, tiempo=60)
    destino = tempfile.mkdtemp(prefix="prig_hub_ver_")
    with tarfile.open(fileobj=io.BytesIO(datos)) as tar:
        if hasattr(tarfile, "data_filter"):
            tar.extractall(destino, filter="data")
        else:                                           # Python sin el filtro: solo archivos y carpetas dentro
            seguros = [m for m in tar.getmembers() if (m.isfile() or m.isdir())
                       and not m.name.startswith("/") and ".." not in m.name.split("/")]
            tar.extractall(destino, members=seguros)
    return destino


def aplicar(carpeta: str, commit: str):
    correr(["reset", "-q", "--hard", commit], cwd=carpeta)
