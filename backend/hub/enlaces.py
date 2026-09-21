"""
Reconocer enlaces: de qué plataforma son, qué tipo de elemento y cuál es su clave estable.

La clave canónica es la identidad de un elemento en Prig Hub. Varias formas de escribir
el mismo enlace dan la misma clave (youtu.be/x, m.youtube.com/watch?v=x&t=30 →
youtube:video:x), así que el progreso no se pierde al reordenar ni se duplica entre packs.

    reconocer(url) → {"url", "plataforma", "tipo", "clave", "ref", "prig"}

`ref` es lo que otras secciones de Prig necesitan para abrirlo (ana/calc para GitHub,
ana/eda para un notebook de Kaggle…). `prig` marca un repositorio que PUEDE ser de Prig
Hub por su nombre (usuario/prig o usuario/prig-algo); se confirma leyendo su prig.yaml.
"""

import re
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit

TIPOS_RECURSO = ("curso", "video", "lista", "notebook", "dataset", "competicion", "repositorio",
                 "archivo", "modelo", "articulo", "ejercicio", "web")
TIPOS = ("persona",) + TIPOS_RECURSO

PLATAFORMAS = {
    "github": "GitHub", "kaggle": "Kaggle", "youtube": "YouTube", "huggingface": "Hugging Face",
    "coursera": "Coursera", "udemy": "Udemy", "edx": "edX", "freecodecamp": "freeCodeCamp",
    "platzi": "Platzi", "exercism": "Exercism", "leetcode": "LeetCode", "arxiv": "arXiv",
    "gitlab": "GitLab", "codeberg": "Codeberg", "linkedin": "LinkedIn", "x": "X", "web": "Web",
}

# Primer tramo de ruta que NO es un usuario en cada sitio (github.com/settings no es una persona)
_RESERVADAS = {
    "github": {"settings", "orgs", "topics", "trending", "explore", "marketplace", "sponsors", "features",
               "about", "pricing", "login", "join", "search", "notifications", "collections", "events", "apps"},
    "kaggle": {"code", "datasets", "competitions", "c", "models", "learn", "discussions", "search",
               "account", "settings", "docs", "rankings", "organizations", "benchmarks", "static"},
    "huggingface": {"models", "datasets", "spaces", "docs", "blog", "learn", "papers", "pricing",
                    "settings", "login", "join", "organizations", "collections", "posts", "tasks"},
}
_SEGURO = re.compile(r"^[A-Za-z0-9_.\-]{1,100}$")
_ID_YT = re.compile(r"^[A-Za-z0-9_\-]{6,20}$")
_QUITAR_PARAMS = re.compile(r"^(utm_.*|fbclid|gclid|si|feature|ref|ref_src|source)$", re.I)


class EnlaceInvalido(ValueError):
    pass


def _host(h: str) -> str:
    h = (h or "").lower().split(":")[0]
    for p in ("www.", "m.", "mobile."):
        if h.startswith(p):
            h = h[len(p):]
    return h


def partes(url: str):
    """ (host, [tramos de la ruta], {parámetros}) de un enlace http(s), o EnlaceInvalido """
    texto = (url or "").strip()
    if not texto:
        raise EnlaceInvalido("El enlace está vacío.")
    if not re.match(r"^https?://", texto, re.I):
        if re.match(r"^[\w.-]+\.[a-z]{2,}(/|$)", texto, re.I):
            texto = "https://" + texto
        else:
            raise EnlaceInvalido(f"«{texto[:80]}» no es un enlace web (http o https).")
    s = urlsplit(texto)
    host = _host(s.hostname or "")
    if not host or "." not in host:
        raise EnlaceInvalido(f"«{texto[:80]}» no tiene un dominio válido.")
    tramos = [t for t in s.path.split("/") if t]
    params = {k: v for k, v in parse_qsl(s.query, keep_blank_values=False)}
    return host, tramos, params, s


def _res(url, plataforma, tipo, id_, ref=None, prig=False) -> Dict[str, Any]:
    return {"url": url, "plataforma": plataforma, "tipo": tipo, "clave": f"{plataforma}:{tipo}:{id_}",
            "ref": ref if ref is not None else id_, "prig": prig}


def _es_prig(repo: str) -> bool:
    r = repo.lower()
    return r == "prig" or r.startswith("prig-")


def _github(url, tramos, params):
    if not tramos:
        return None
    u = tramos[0].lower()
    if u in _RESERVADAS["github"] or not _SEGURO.match(u):
        return None
    if len(tramos) == 1:
        return _res(url, "github", "persona", u)
    repo = tramos[1].lower()
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not _SEGURO.match(repo):
        return None
    ref = f"{u}/{repo}"
    if len(tramos) >= 4 and tramos[2] in ("blob", "tree"):
        ruta = "/".join(tramos[4:])
        if tramos[2] == "blob" and ruta:
            return _res(url, "github", "archivo", f"{ref}/{ruta}", ref=ref)
    return _res(url, "github", "repositorio", ref, prig=_es_prig(repo))


def _git_generico(plataforma):
    def reconocer(url, tramos, params):
        if len(tramos) < 2 or not all(_SEGURO.match(t) for t in tramos[:2]):
            return _res(url, plataforma, "persona", tramos[0].lower()) if tramos and _SEGURO.match(tramos[0]) else None
        repo = tramos[1].lower().removesuffix(".git")
        return _res(url, plataforma, "repositorio", f"{tramos[0].lower()}/{repo}", prig=_es_prig(repo))
    return reconocer


def _kaggle(url, tramos, params):
    if not tramos:
        return None
    t = [x.lower() for x in tramos]
    if t[0] == "code" and len(t) >= 3:
        return _res(url, "kaggle", "notebook", f"{t[1]}/{t[2]}")
    if t[0] == "datasets" and len(t) >= 3:
        return _res(url, "kaggle", "dataset", f"{t[1]}/{t[2]}")
    if t[0] in ("competitions", "c") and len(t) >= 2:
        return _res(url, "kaggle", "competicion", t[1])
    if t[0] == "models" and len(t) >= 3:
        return _res(url, "kaggle", "modelo", f"{t[1]}/{t[2]}")
    if t[0] == "learn" and len(t) >= 2:
        return _res(url, "kaggle", "curso", t[1])
    if t[0] in _RESERVADAS["kaggle"]:
        return None
    if len(t) >= 2 and _SEGURO.match(t[1]):                 # kaggle.com/<usuario>/<notebook> (forma antigua)
        return _res(url, "kaggle", "notebook", f"{t[0]}/{t[1]}")
    return _res(url, "kaggle", "persona", t[0]) if _SEGURO.match(t[0]) else None


def _youtube(url, tramos, params, host):
    if host == "youtu.be" and tramos and _ID_YT.match(tramos[0]):
        return _res(url, "youtube", "video", tramos[0])
    if tramos and tramos[0] == "playlist" and params.get("list"):
        return _res(url, "youtube", "lista", params["list"])
    if tramos and tramos[0] == "watch" and _ID_YT.match(params.get("v", "")):
        return _res(url, "youtube", "video", params["v"])
    if len(tramos) >= 2 and tramos[0] in ("shorts", "live", "embed") and _ID_YT.match(tramos[1]):
        return _res(url, "youtube", "video", tramos[1])
    if tramos and tramos[0].startswith("@"):
        return _res(url, "youtube", "persona", tramos[0].lower())
    if len(tramos) >= 2 and tramos[0] in ("channel", "c", "user"):
        return _res(url, "youtube", "persona", f"{tramos[0]}/{tramos[1] if tramos[0] == 'channel' else tramos[1].lower()}")
    return None


def _huggingface(url, tramos, params):
    if not tramos:
        return None
    t = tramos
    if t[0] in ("datasets", "spaces") and len(t) >= 3:
        return _res(url, "huggingface", "dataset" if t[0] == "datasets" else "web", f"{t[0]}/{t[1]}/{t[2]}".lower())
    if t[0] == "learn" and len(t) >= 2:
        return _res(url, "huggingface", "curso", t[1].lower())
    if t[0] in _RESERVADAS["huggingface"]:
        return None
    if len(t) >= 2:
        return _res(url, "huggingface", "modelo", f"{t[0]}/{t[1]}".lower())
    return _res(url, "huggingface", "persona", t[0].lower())


def _cursos(url, host, tramos):
    t = [x.lower() for x in tramos]
    if host.endswith("coursera.org") and len(t) >= 2 and t[0] in ("learn", "specializations", "professional-certificates", "projects"):
        return _res(url, "coursera", "curso", f"{t[0]}/{t[1]}")
    if host.endswith("udemy.com") and len(t) >= 2 and t[0] == "course":
        return _res(url, "udemy", "curso", t[1])
    if host.endswith("edx.org") and len(t) >= 2 and t[0] in ("learn", "course", "professional-certificate"):
        return _res(url, "edx", "curso", "/".join(t[:3]))
    if host.endswith("freecodecamp.org") and t and t[0] == "learn":
        return _res(url, "freecodecamp", "curso", "/".join(t[1:3]) or "learn")
    if host.endswith("platzi.com") and len(t) >= 2 and t[0] == "cursos":
        return _res(url, "platzi", "curso", t[1])
    if host.endswith("exercism.org") and len(t) >= 4 and t[0] == "tracks" and t[2] == "exercises":
        return _res(url, "exercism", "ejercicio", f"{t[1]}/{t[3]}")
    if host.endswith("leetcode.com") and len(t) >= 2 and t[0] == "problems":
        return _res(url, "leetcode", "ejercicio", t[1])
    if host == "arxiv.org" and len(t) >= 2 and t[0] in ("abs", "pdf"):
        return _res(url, "arxiv", "articulo", re.sub(r"(v\d+)?(\.pdf)?$", "", t[1]))
    if host.endswith("linkedin.com") and len(t) >= 2 and t[0] == "in":
        return _res(url, "linkedin", "persona", t[1])
    if host in ("x.com", "twitter.com") and len(t) == 1 and _SEGURO.match(t[0]):
        return _res(url, "x", "persona", t[0])
    return None


def normalizar(url: str) -> str:
    """ El enlace limpio: https, sin www., sin barra final, sin parámetros de seguimiento ni ancla """
    host, tramos, params, s = partes(url)
    limpios = {k: v for k, v in params.items() if not _QUITAR_PARAMS.match(k)}
    ruta = "/" + "/".join(tramos) if tramos else ""
    consulta = ("?" + urlencode(sorted(limpios.items()))) if limpios else ""
    return f"https://{host}{ruta}{consulta}"


def reconocer(url: str) -> Dict[str, Any]:
    """ Plataforma, tipo y clave estable de un enlace. Todo enlace http(s) válido se reconoce
    (como mínimo, «web»); lanza EnlaceInvalido si no es un enlace """
    limpio = normalizar(url)
    host, tramos, params, _ = partes(limpio)
    r: Optional[Dict[str, Any]] = None
    if host == "github.com":
        r = _github(limpio, tramos, params)
    elif host in ("gitlab.com", "codeberg.org"):
        r = _git_generico("gitlab" if host == "gitlab.com" else "codeberg")(limpio, tramos, params)
    elif host == "kaggle.com":
        r = _kaggle(limpio, tramos, params)
    elif host in ("youtube.com", "youtu.be", "music.youtube.com"):
        r = _youtube(limpio, tramos, params, host)
    elif host in ("huggingface.co", "hf.co"):
        r = _huggingface(limpio, tramos, params)
    else:
        r = _cursos(limpio, host, tramos)
    if r:
        return r
    id_ = host + ("/" + "/".join(tramos) if tramos else "")
    consulta = urlsplit(limpio).query
    return _res(limpio, "web", "web" if not tramos else "articulo", (id_ + ("?" + consulta if consulta else "")).lower())


def es_persona(info: Dict[str, Any]) -> bool:
    return info.get("tipo") == "persona"


def url_git(url: str) -> Optional[str]:
    """ La URL para clonar un repositorio de GitHub, GitLab o Codeberg, o None """
    try:
        info = reconocer(url)
    except EnlaceInvalido:
        return None
    if info["tipo"] != "repositorio":
        return None
    dominio = {"github": "github.com", "gitlab": "gitlab.com", "codeberg": "codeberg.org"}.get(info["plataforma"])
    return f"https://{dominio}/{info['ref']}.git" if dominio else None
