"""
Lo que Prig Hub necesita de GitHub, sobre el mismo cliente que la sección GitHub
(github_lector: su token guardado con permisos 600 y su URL de API, que las pruebas cambian).

  · usuario, repo, crear_repo y temas: para publicar (necesitan token);
  · es_hub: ¿tiene prig.yaml? Se lee el archivo en crudo, que no gasta cuota de la API;
  · descubrir: repositorios con el topic prig-perfil o prig-pack.
"""

import re
from typing import Any, Dict, List, Optional

import requests

import github_lector as gl

from . import enlaces


class ErrorGitHubHub(Exception):
    pass


def _cab(token: Optional[str]) -> Dict[str, str]:
    return {**gl.UA, **({"Authorization": f"Bearer {token}"} if token else {})}


class Cuenta:
    """ Operaciones con la cuenta del usuario: necesitan token """

    def __init__(self, token: str):
        self.token = token

    def _pedir(self, metodo: str, ruta: str, **kw):
        try:
            r = requests.request(metodo, f"{gl.API}/{ruta}", headers=_cab(self.token), timeout=30, **kw)
        except requests.RequestException:
            raise ErrorGitHubHub("Sin conexión con GitHub.")
        if r.status_code == 401:
            raise ErrorGitHubHub("GitHub no aceptó el token: vuelve a pegarlo en la sección GitHub.")
        return r

    def usuario(self) -> Dict[str, Any]:
        r = self._pedir("GET", "user")
        if r.status_code != 200:
            raise ErrorGitHubHub(f"No se pudo leer tu cuenta de GitHub ({r.status_code}).")
        d = r.json()
        return {"login": d["login"], "id": d["id"]}

    def repo(self, login: str, nombre: str) -> Optional[Dict[str, Any]]:
        r = self._pedir("GET", f"repos/{login}/{nombre}")
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise ErrorGitHubHub(f"GitHub respondió {r.status_code} al buscar {login}/{nombre}.")
        return r.json()

    def crear_repo(self, nombre: str, descripcion: str) -> Dict[str, Any]:
        r = self._pedir("POST", "user/repos", json={"name": nombre, "description": descripcion, "private": False,
                                                     "has_wiki": False, "auto_init": False})
        if r.status_code in (403, 404):
            raise ErrorGitHubHub("El token no tiene permiso para crear repositorios. Crea en GitHub un repositorio "
                                 f"vacío llamado «{nombre}» (o da al token permiso «Administration: write») y vuelve a publicar.")
        if r.status_code == 422:
            raise ErrorGitHubHub(f"GitHub no dejó crear «{nombre}»: {(r.json().get('errors') or [{}])[0].get('message', 'nombre no válido')}.")
        if r.status_code not in (200, 201):
            raise ErrorGitHubHub(f"GitHub respondió {r.status_code} al crear el repositorio.")
        return r.json()

    def temas(self, login: str, nombre: str, temas: List[str]):
        limpios = []
        for t in temas:
            t = re.sub(r"[^a-z0-9-]+", "-", str(t).lower()).strip("-")[:50]
            if t and t not in limpios:
                limpios.append(t)
        self._pedir("PUT", f"repos/{login}/{nombre}/topics", json={"names": limpios[:20]})


def _crudo(info: Dict[str, Any], archivo: str) -> Optional[str]:
    ref = info["ref"]
    if info["plataforma"] == "github":
        return f"{gl.RAW}/{ref}/HEAD/{archivo}"
    if info["plataforma"] == "gitlab":
        return f"https://gitlab.com/{ref}/-/raw/HEAD/{archivo}"
    if info["plataforma"] == "codeberg":
        return f"https://codeberg.org/{ref}/raw/branch/main/{archivo}"
    return None


def es_hub(url: str) -> bool:
    """ ¿El repositorio tiene un prig.yaml? (en crudo: no cuenta para el límite de la API) """
    info = enlaces.reconocer(url)
    if info["tipo"] != "repositorio":
        return False
    crudo = _crudo(info, "prig.yaml")
    if not crudo:
        return False
    try:
        r = requests.get(crudo, headers={"User-Agent": gl.UA["User-Agent"]}, timeout=10)
    except requests.RequestException:
        return False
    return r.status_code == 200 and "tipo" in r.text[:4000] and len(r.content) < 64 * 1024


def descubrir(consulta: str = "", tipo: str = "pack", pagina: int = 1) -> Dict[str, Any]:
    tema = "prig-perfil" if tipo == "perfil" else "prig-pack"
    q = f"topic:{tema} {(consulta or '').strip()}".strip()
    try:
        d = gl._api("search/repositories", {"q": q, "sort": "stars", "per_page": 30, "page": max(1, int(pagina))})
    except gl.ErrorGitHub as e:
        raise ErrorGitHubHub(str(e))
    salida = []
    for r in d.get("items", []):
        salida.append({"ref": r["full_name"], "url": r["html_url"], "titulo": r["name"],
                       "descripcion": r.get("description") or "", "estrellas": r.get("stargazers_count", 0),
                       "actualizado": r.get("pushed_at"), "temas": r.get("topics") or [],
                       "dueno": (r.get("owner") or {}).get("login"), "avatar": (r.get("owner") or {}).get("avatar_url")})
    return {"total": d.get("total_count", 0), "repos": salida}
