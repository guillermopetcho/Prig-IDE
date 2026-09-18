"""
GitHub: buscar repositorios, leerlos con un modelo al lado y bajarlos al proyecto.

Medido contra GitHub (sin cuenta):
    api.github.com/search/repositories    10 búsquedas por minuto
    api.github.com/repos/…                60 consultas por hora (con token, 5000)
    raw.githubusercontent.com/…           archivos en crudo: no cuenta para ese límite
    codeload.github.com/…/zip/…           el repositorio entero en zip: tampoco

Abrir un repositorio cuesta 3 consultas (ficha, lenguajes y árbol de archivos) y se
guarda un día en disco, así que volver a él no gasta nada. Los archivos y el README se
leen en crudo. Con un token (GITHUB_TOKEN, GH_TOKEN o el que se guarde desde Prig, con
permisos 600) los límites suben; para repositorios públicos no hace falta ningún permiso.

El modelo explica el repositorio en conjunto (con el README, la estructura y el código
de los archivos clave) o archivo a archivo. Las explicaciones se guardan y se exportan
a Markdown o a PDF («código explicado»: cada archivo con su explicación debajo).
"""

import hashlib
import io
import json
import os
import re
import shutil
import threading
import time
import zipfile
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import requests

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
CODELOAD = "https://codeload.github.com"
UA = {"User-Agent": "Prig-IDE (lector de repositorios; uso educativo local)", "Accept": "application/vnd.github+json"}
REF_VALIDA = re.compile(r"^[A-Za-z0-9_.\-]{1,100}/[A-Za-z0-9_.\-]{1,100}$")
ORDENES = {"estrellas": "stars", "actualizados": "updated", "forks": "forks", "relevancia": ""}
MAX_ARCHIVO = 400_000           # bytes: más que esto no se lee (binarios, datos, minificados)
CARPETA_REPOS = "github_repos"
CARPETA_EXPORT = "github_explicaciones"
BINARIOS = re.compile(r"\.(png|jpe?g|gif|webp|ico|bmp|pdf|zip|gz|tar|whl|so|dll|exe|bin|pkl|pt|pth|h5|onnx|npy|npz|parquet|mp[34]|wav|ttf|woff2?|eot|jar|class|pyc)$", re.I)
CLAVE_ARCHIVOS = re.compile(r"(^|/)(readme[^/]*|setup\.py|pyproject\.toml|requirements[^/]*\.txt|package\.json|cargo\.toml|go\.mod|"
                            r"main\.[a-z]+|app\.[a-z]+|__main__\.py|index\.[jt]sx?|cli\.py|manage\.py|dockerfile|makefile)$", re.I)


class ErrorGitHub(Exception):
    pass


def carpeta() -> str:
    return os.environ.get("PRIG_GITHUB_DIR") or os.path.expanduser("~/.prig_github")


def ruta_token() -> str:
    return os.environ.get("PRIG_GITHUB_CREDENCIALES") or os.path.expanduser("~/.prig_github.json")


def _leer_json(ruta: str) -> Optional[Any]:
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError, OSError):
        return None


def _escribir_json(ruta: str, datos: Any):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta + ".tmp", "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False)
    os.replace(ruta + ".tmp", ruta)


_cerrojo = threading.RLock()

# ===========================================================================
# Token (opcional)
# ===========================================================================

def token() -> Optional[Dict[str, str]]:
    guardado = _leer_json(ruta_token()) or {}
    if guardado.get("token"):
        return {"token": guardado["token"], "origen": "Prig"}
    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(var):
            return {"token": os.environ[var], "origen": f"variable {var}"}
    return None


def _cabeceras() -> Dict[str, str]:
    t = token()
    return {**UA, **({"Authorization": f"Bearer {t['token']}"} if t else {})}


def estado() -> Dict[str, Any]:
    t = token()
    return {"con_token": bool(t), "origen": (t or {}).get("origen"),
            "limite": "5000 consultas por hora" if t else "60 consultas por hora y 10 búsquedas por minuto",
            "url_token": "https://github.com/settings/tokens?type=beta"}


def guardar_token(texto: str) -> Dict[str, Any]:
    t = (texto or "").strip()
    if not t or re.search(r"\s", t) or len(t) < 20:
        raise ErrorGitHub("Pega el token completo (empieza por github_pat_ o ghp_).")
    r = _get(f"{API}/rate_limit", cabeceras={**UA, "Authorization": f"Bearer {t}"})
    if r.status_code == 401:
        raise ErrorGitHub("GitHub no aceptó ese token.")
    fd = os.open(ruta_token() + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"token": t, "guardado": datetime.now().isoformat(timespec="seconds")}, f)
    os.replace(ruta_token() + ".tmp", ruta_token())
    os.chmod(ruta_token(), 0o600)
    return estado()


def borrar_token() -> Dict[str, Any]:
    try:
        os.remove(ruta_token())
    except FileNotFoundError:
        pass
    return estado()


# ===========================================================================
# Peticiones
# ===========================================================================

def _get(url: str, params: Optional[Dict[str, Any]] = None, cabeceras: Optional[Dict[str, str]] = None, **kw):
    try:
        return requests.get(url, params=params, headers=cabeceras or _cabeceras(), timeout=kw.pop("timeout", 30), **kw)
    except requests.RequestException:
        raise ErrorGitHub("Sin conexión con GitHub: comprueba internet.")


def _api(ruta: str, params: Optional[Dict[str, Any]] = None) -> Any:
    r = _get(f"{API}/{ruta}", params)
    if r.status_code in (403, 429) and (r.headers.get("X-RateLimit-Remaining") == "0" or r.status_code == 429):
        reset = int(r.headers.get("X-RateLimit-Reset") or 0)
        minutos = max(1, round((reset - time.time()) / 60)) if reset else None
        recurso = r.headers.get("X-RateLimit-Resource") or ""
        raise ErrorGitHub(f"GitHub limitó las {'búsquedas' if recurso == 'search' else 'consultas'} sin cuenta"
                          + (f": vuelve a probar en {minutos} min" if minutos else "")
                          + ". Con un token gratuito de GitHub el límite sube mucho.")
    if r.status_code == 401:
        raise ErrorGitHub("GitHub no aceptó el token guardado: vuelve a pegarlo o bórralo.")
    if r.status_code == 404:
        raise ErrorGitHub("Ese repositorio no existe o es privado.")
    if r.status_code == 422:
        raise ErrorGitHub("GitHub no entendió la búsqueda: prueba con otras palabras.")
    if r.status_code != 200:
        raise ErrorGitHub(f"GitHub respondió {r.status_code}.")
    return r.json()


# ===========================================================================
# Buscar
# ===========================================================================

def ref_desde(texto: str) -> str:
    """ «dueño/repo» a partir de un enlace (con /tree/…, /blob/…, .git) o de la referencia """
    t = (texto or "").strip()
    m = re.search(r"github\.com[/:]([A-Za-z0-9_.\-]+)/([A-Za-z0-9_.\-]+)", t)
    ref = f"{m.group(1)}/{m.group(2)}" if m else t.strip("/")
    ref = re.sub(r"\.git$", "", ref)
    if not REF_VALIDA.match(ref) or ".." in ref:
        raise ErrorGitHub("Eso no es un repositorio de GitHub: pega un enlace como github.com/usuario/repositorio.")
    return ref


def _corto(r: Dict[str, Any]) -> Dict[str, Any]:
    return {"ref": r.get("full_name"), "nombre": r.get("name"), "dueno": (r.get("owner") or {}).get("login"),
            "avatar": (r.get("owner") or {}).get("avatar_url"), "descripcion": r.get("description") or "",
            "estrellas": r.get("stargazers_count"), "forks": r.get("forks_count"), "lenguaje": r.get("language"),
            "temas": (r.get("topics") or [])[:10], "actualizado": r.get("pushed_at") or r.get("updated_at"),
            "licencia": ((r.get("license") or {}).get("spdx_id") or (r.get("license") or {}).get("name")),
            "rama": r.get("default_branch"), "kb": r.get("size"), "issues": r.get("open_issues_count"),
            "web": r.get("homepage") or "", "archivado": bool(r.get("archived")), "fork": bool(r.get("fork")),
            "url": r.get("html_url") or f"https://github.com/{r.get('full_name')}"}


_cache: Dict[str, Any] = {}


def buscar(consulta: str, lenguaje: str = "", orden: str = "estrellas", pagina: int = 1,
           estrellas_min: int = 0, tema: str = "") -> Dict[str, Any]:
    partes = [consulta.strip()[:200]] if consulta.strip() else []
    if lenguaje.strip():
        partes.append(f"language:{lenguaje.strip()}")
    if estrellas_min:
        partes.append(f"stars:>={int(estrellas_min)}")
    if tema.strip():
        partes.append(f"topic:{tema.strip()}")
    if not partes:
        raise ErrorGitHub("Escribe qué buscar.")
    params = {"q": " ".join(partes), "per_page": 20, "page": max(1, int(pagina))}
    if ORDENES.get(orden):
        params.update(sort=ORDENES[orden], order="desc")
    clave = json.dumps(params, sort_keys=True)
    if clave in _cache and time.time() - _cache[clave][0] < 600:
        return _cache[clave][1]
    d = _api("search/repositories", params)
    items = d.get("items") or []
    resultado = {"repos": [_corto(r) for r in items], "total": d.get("total_count", 0), "pagina": params["page"],
                 "hay_mas": params["page"] * 20 < min(d.get("total_count", 0), 1000)}
    _cache[clave] = (time.time(), resultado)
    return resultado


# ===========================================================================
# Abrir un repositorio
# ===========================================================================

def _ruta_repo(ref: str) -> str:
    return os.path.join(carpeta(), "repos", ref.replace("/", "__") + ".json")


def abrir(texto: str, refrescar: bool = False) -> Dict[str, Any]:
    """ Ficha, lenguajes, árbol de archivos y README. Un día en disco. """
    ref = ref_desde(texto)
    ruta = _ruta_repo(ref)
    if not refrescar and os.path.exists(ruta) and time.time() - os.path.getmtime(ruta) < 86400:
        guardado = _leer_json(ruta)
        if guardado:
            return guardado
    meta = _api(f"repos/{ref}")
    info = _corto(meta)
    ref = info["ref"]                                         # con las mayúsculas buenas
    try:
        lenguajes = _api(f"repos/{ref}/languages")
    except ErrorGitHub:
        lenguajes = {}
    arbol = _api(f"repos/{ref}/git/trees/{info['rama']}", {"recursive": 1})
    archivos = [{"ruta": t["path"], "bytes": t.get("size") or 0, "sha": t.get("sha")}
                for t in arbol.get("tree") or [] if t.get("type") == "blob"]
    total = sum(lenguajes.values()) or 1
    info.update(
        lenguajes=[{"nombre": k, "pct": round(100 * v / total, 1)} for k, v in sorted(lenguajes.items(), key=lambda x: -x[1])][:8],
        archivos=archivos[:5000], truncado=bool(arbol.get("truncated")) or len(archivos) > 5000,
        descargado=datetime.now().isoformat(timespec="seconds"))
    readme = next((a["ruta"] for a in archivos if re.fullmatch(r"readme(\.(md|rst|txt|markdown))?", a["ruta"], re.I)), None)
    info["readme_ruta"] = readme
    info["readme"] = _crudo(ref, info["rama"], readme)[:60000] if readme else ""
    _escribir_json(_ruta_repo(ref), info)
    if ref != ref_desde(texto):
        _escribir_json(ruta, info)
    return info


def _crudo(ref: str, rama: str, ruta: str) -> str:
    r = _get(f"{RAW}/{ref}/{rama}/{requests.utils.quote(ruta)}", cabeceras=UA)
    if r.status_code == 404:
        raise ErrorGitHub(f"No se encontró {ruta} en el repositorio.")
    if r.status_code != 200:
        raise ErrorGitHub(f"GitHub respondió {r.status_code} al leer {ruta}.")
    return r.content.decode("utf-8", errors="replace")


def leer_archivo(texto: str, ruta: str) -> Dict[str, Any]:
    info = abrir(texto)
    a = next((x for x in info["archivos"] if x["ruta"] == ruta), None)
    if a is None:
        raise ErrorGitHub("Ese archivo no está en el repositorio.")
    if BINARIOS.search(ruta):
        return {"ruta": ruta, "bytes": a["bytes"], "binario": True, "contenido": ""}
    if a["bytes"] > MAX_ARCHIVO:
        return {"ruta": ruta, "bytes": a["bytes"], "grande": True, "contenido": ""}
    cache = os.path.join(carpeta(), "archivos", info["ref"].replace("/", "__"), (a.get("sha") or hashlib.sha1(ruta.encode()).hexdigest()) + ".txt")
    try:
        with open(cache, encoding="utf-8") as f:
            contenido = f.read()
    except FileNotFoundError:
        contenido = _crudo(info["ref"], info["rama"], ruta)
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache, "w", encoding="utf-8") as f:
            f.write(contenido)
    if "\x00" in contenido[:2000]:
        return {"ruta": ruta, "bytes": a["bytes"], "binario": True, "contenido": ""}
    return {"ruta": ruta, "bytes": a["bytes"], "sha": a.get("sha"), "contenido": contenido,
            "lineas": len(contenido.splitlines()) or 1, "lenguaje": _lenguaje(ruta)}


def _lenguaje(ruta: str) -> str:
    ext = ruta.rsplit(".", 1)[-1].lower() if "." in ruta else ""
    return {"py": "python", "js": "javascript", "mjs": "javascript", "ts": "typescript", "tsx": "typescript", "jsx": "javascript",
            "md": "markdown", "json": "json", "yml": "yaml", "yaml": "yaml", "toml": "toml", "sh": "bash", "go": "go",
            "rs": "rust", "java": "java", "c": "c", "h": "c", "cpp": "cpp", "hpp": "cpp", "cs": "csharp", "rb": "ruby",
            "php": "php", "html": "html", "css": "css", "sql": "sql", "r": "r", "ipynb": "json", "kt": "kotlin",
            "swift": "swift", "scala": "scala", "lua": "lua", "jl": "julia"}.get(ext, "plaintext")


# ===========================================================================
# El modelo
# ===========================================================================

NIVELES = {
    "principiante": "El alumno está empezando: explica cada término técnico la primera vez y usa analogías sencillas.",
    "intermedio": "El alumno programa con soltura: céntrate en el diseño, las decisiones y lo que no es obvio.",
    "avanzado": "El alumno es avanzado: ve directo a la arquitectura, los compromisos y los detalles finos.",
}

SISTEMA_REPO = """Eres un ingeniero de software senior que presenta un repositorio de GitHub a un alumno
que va a leerlo. En español, concreto, apoyándote SOLO en lo que se te da (README, estructura,
lenguajes y el código de los archivos clave). Usa exactamente estas secciones en markdown:

## Qué es
Qué problema resuelve y para quién, en 2-4 frases.
## Cómo está organizado
Las carpetas y archivos importantes y el papel de cada uno (cita las rutas entre `comillas de código`).
## Cómo funciona
El flujo principal: por dónde entra la ejecución y qué pasa después.
## Tecnologías y conceptos
Lenguajes, librerías y patrones que usa, y qué aprender para entenderlo.
## Por dónde empezar a leer
Un orden de lectura de 4-6 archivos concretos, con el porqué de cada uno.
## Cómo probarlo
Los pasos para instalarlo y ejecutarlo en local, si se deducen del repositorio.

No inventes archivos ni funciones que no aparezcan."""

SISTEMA_ARCHIVO = """Eres un ingeniero de software senior que lee un archivo de un repositorio de GitHub JUNTO
al alumno. En español y apoyándote en el código que se te da. Usa estas secciones en markdown:

### Qué hace
El propósito del archivo en 2-3 frases.
### Partes importantes
Las funciones, clases o bloques clave en orden, qué hace cada uno (cita el código entre `comillas`).
### Cómo encaja en el proyecto
Quién lo usa o a quién llama, según la estructura del repositorio.
### Conceptos
Las ideas de programación que aparecen y merecen aprenderse.
### Para pensar
Una pregunta o un pequeño cambio que el alumno podría intentar."""


def estructura(info: Dict[str, Any], max_lineas: int = 120) -> str:
    """ El árbol resumido: carpetas con su número de archivos y los archivos de la raíz """
    carpetas: Dict[str, int] = {}
    raiz = []
    for a in info["archivos"]:
        partes = a["ruta"].split("/")
        if len(partes) == 1:
            raiz.append(a["ruta"])
        else:
            for n in range(1, min(len(partes), 3)):
                carpetas["/".join(partes[:n]) + "/"] = carpetas.get("/".join(partes[:n]) + "/", 0) + 1
    lineas = [f"{c}  ({n} archivos)" for c, n in sorted(carpetas.items())] + sorted(raiz)
    return "\n".join(lineas[:max_lineas]) + ("\n…" if len(lineas) > max_lineas else "")


def archivos_clave(info: Dict[str, Any], limite: int = 8) -> List[str]:
    """ Los que mejor cuentan el proyecto: configuración, puntos de entrada y el código de la raíz del paquete """
    codigo = [a for a in info["archivos"] if not BINARIOS.search(a["ruta"]) and 0 < a["bytes"] <= 60_000]
    clave = [a["ruta"] for a in codigo if CLAVE_ARCHIVOS.search(a["ruta"]) and a["ruta"] != info.get("readme_ruta")]
    clave.sort(key=lambda r: (r.count("/"), r))
    fuente = [a for a in codigo if _lenguaje(a["ruta"]) not in ("plaintext", "markdown", "json", "yaml", "toml")
              and not re.search(r"(^|/)(tests?|docs?|examples?|\.github)/", a["ruta"]) and a["ruta"] not in clave]
    fuente.sort(key=lambda a: (a["ruta"].count("/"), -a["bytes"]))
    return (clave[:4] + [a["ruta"] for a in fuente])[:limite]


def contexto_repo(info: Dict[str, Any], presupuesto: int = 14000) -> str:
    partes = [f"REPOSITORIO: {info['ref']} · {info.get('descripcion') or 'sin descripción'}",
              f"Lenguajes: {', '.join(f'{l['nombre']} {l['pct']}%' for l in info.get('lenguajes', []))}",
              f"Temas: {', '.join(info.get('temas') or []) or '-'} · Estrellas: {info.get('estrellas')} · Licencia: {info.get('licencia') or '-'}",
              f"ESTRUCTURA ({len(info['archivos'])} archivos):\n{estructura(info)}"]
    if info.get("readme"):
        partes.append("README:\n" + re.sub(r"!\[[^\]]*\]\([^)]*\)|<img[^>]*>", "", info["readme"])[:4000])
    usado = sum(len(p) for p in partes)
    for ruta in archivos_clave(info):
        if usado > presupuesto:
            break
        try:
            a = leer_archivo(info["ref"], ruta)
        except ErrorGitHub:
            continue
        if not a.get("contenido"):
            continue
        trozo = a["contenido"][:max(800, min(3500, presupuesto - usado))]
        partes.append(f"--- {ruta} ---\n{trozo}")
        usado += len(trozo)
    return "\n\n".join(partes)


def explicar_repo(ai, modelo: str, info: Dict[str, Any]):
    from desafios.tutor import flujo
    return (yield from flujo(ai, modelo, contexto_repo(info), SISTEMA_REPO, temperatura=0.3, pensar=True))


def explicar_archivo(ai, modelo: str, info: Dict[str, Any], ruta: str, nivel: str = "intermedio"):
    from desafios.tutor import flujo
    a = leer_archivo(info["ref"], ruta)
    if not a.get("contenido"):
        raise ErrorGitHub("Ese archivo no se puede explicar (es binario o demasiado grande).")
    prompt = (f"REPOSITORIO: {info['ref']} · {info.get('descripcion') or ''}\n\nESTRUCTURA:\n{estructura(info, 60)}\n\n"
              f"ARCHIVO {ruta} ({a['lineas']} líneas):\n{a['contenido'][:12000]}"
              + ("\n… (archivo recortado)" if len(a["contenido"]) > 12000 else ""))
    sistema = SISTEMA_ARCHIVO + "\n\n" + NIVELES.get(nivel, NIVELES["intermedio"])
    return (yield from flujo(ai, modelo, prompt, sistema, temperatura=0.3))


def preguntar(ai, modelo: str, info: Dict[str, Any], ruta: Optional[str], mensajes: List[Dict[str, str]]):
    from desafios.tutor import flujo
    sistema = ("Eres un ingeniero de software senior que lee con el alumno un repositorio de GitHub. Responde en español, "
               "claro y breve (menos de 200 palabras), apoyándote en el código. Si algo no está en lo que ves, dilo.")
    contexto = f"REPOSITORIO: {info['ref']} · {info.get('descripcion') or ''}\n\nESTRUCTURA:\n{estructura(info, 60)}"
    if ruta:
        try:
            a = leer_archivo(info["ref"], ruta)
            contexto += f"\n\nARCHIVO ABIERTO {ruta}:\n{a.get('contenido', '')[:8000]}"
        except ErrorGitHub:
            pass
    resumen = explicacion_guardada(info, None, "", modelo) or next(iter(_explicaciones_repo(info)), None)
    if resumen:
        contexto += f"\n\nRESUMEN DEL REPOSITORIO:\n{resumen[:2500]}"
    historial = "\n".join(f"{'Alumno' if m.get('rol') == 'usuario' else 'Profesor'}: {str(m.get('texto'))[:1500]}" for m in (mensajes or [])[-10:])
    return (yield from flujo(ai, modelo, f"{contexto}\n\nCONVERSACIÓN:\n{historial}\nProfesor:", sistema, temperatura=0.4))


# ------------------------------------------------------------------ explicaciones guardadas

def _ruta_explicaciones(ref: str) -> str:
    return os.path.join(carpeta(), "explicaciones", ref.replace("/", "__") + ".json")


def explicaciones(ref: str) -> Dict[str, Any]:
    return _leer_json(_ruta_explicaciones(ref)) or {}


def _clave(info: Dict[str, Any], ruta: Optional[str], nivel: str, modelo: str) -> str:
    if ruta is None:
        return f"repo:{modelo}:{hashlib.sha1(json.dumps([a['sha'] for a in info['archivos'][:400]]).encode()).hexdigest()[:10]}"
    sha = next((a.get("sha") for a in info["archivos"] if a["ruta"] == ruta), "") or ""
    return f"archivo:{ruta}:{nivel}:{modelo}:{sha[:10]}"


def explicacion_guardada(info: Dict[str, Any], ruta: Optional[str], nivel: str, modelo: str) -> Optional[str]:
    return (explicaciones(info["ref"]).get(_clave(info, ruta, nivel, modelo)) or {}).get("texto")


def _explicaciones_repo(info: Dict[str, Any]) -> List[str]:
    e = explicaciones(info["ref"])
    return [v["texto"] for k, v in sorted(e.items(), key=lambda kv: kv[1].get("fecha") or "", reverse=True) if k.startswith("repo:")]


def guardar_explicacion(info: Dict[str, Any], ruta: Optional[str], nivel: str, modelo: str, texto: str):
    with _cerrojo:
        datos = explicaciones(info["ref"])
        datos[_clave(info, ruta, nivel, modelo)] = {"texto": texto, "ruta": ruta, "nivel": nivel, "modelo": modelo,
                                                   "fecha": datetime.now().isoformat(timespec="seconds")}
        _escribir_json(_ruta_explicaciones(info["ref"]), datos)


def explicadas(info: Dict[str, Any]) -> Dict[str, Any]:
    """ Para la interfaz: la del repositorio y, por archivo, la más reciente que sigue valiendo """
    vigentes = {a["ruta"]: (a.get("sha") or "")[:10] for a in info["archivos"]}
    repo, por_archivo = None, {}
    for clave, e in explicaciones(info["ref"]).items():
        if clave.startswith("repo:"):
            if repo is None or e["fecha"] > repo["fecha"]:
                repo = e
            continue
        ruta = e.get("ruta")
        if ruta not in vigentes or not clave.endswith(":" + vigentes[ruta]):
            continue                                        # el archivo cambió desde entonces
        if ruta not in por_archivo or e["fecha"] > por_archivo[ruta]["fecha"]:
            por_archivo[ruta] = e
    return {"repo": repo, "archivos": por_archivo}


# ===========================================================================
# Guardados y descargas
# ===========================================================================

def _ruta_guardados() -> str:
    return os.path.join(carpeta(), "guardados.json")


def guardados() -> List[Dict[str, Any]]:
    return _leer_json(_ruta_guardados()) or []


def guardar(texto: str, nota: str = "") -> List[Dict[str, Any]]:
    info = abrir(texto)
    with _cerrojo:
        lista = [g for g in guardados() if g["ref"] != info["ref"]]
        lista.insert(0, {**{k: info.get(k) for k in ("ref", "nombre", "dueno", "avatar", "descripcion", "estrellas",
                                                      "lenguaje", "temas", "url")},
                         "nota": (nota or "").strip()[:1000], "guardado": datetime.now().isoformat(timespec="seconds")})
        _escribir_json(_ruta_guardados(), lista)
    return lista


def quitar(ref: str) -> List[Dict[str, Any]]:
    with _cerrojo:
        lista = [g for g in guardados() if g["ref"].lower() != ref.lower()]
        _escribir_json(_ruta_guardados(), lista)
    return lista


def carpeta_local(ref: str, workspace: str) -> str:
    return os.path.join(workspace, CARPETA_REPOS, ref.split("/")[1])


def local(ref: str, workspace: str) -> Optional[Dict[str, Any]]:
    raiz = carpeta_local(ref, workspace)
    if not os.path.isdir(raiz):
        return None
    n, total = 0, 0
    for base, _, nombres in os.walk(raiz):
        n += len(nombres)
        total += sum(os.path.getsize(os.path.join(base, x)) for x in nombres)
    return {"carpeta": raiz, "relativa": os.path.relpath(raiz, workspace), "archivos": n, "bytes": total}


def descargar(texto: str, workspace: str, avisar: Callable[[Dict[str, Any]], None] = lambda e: None,
              cancelar: Optional[threading.Event] = None) -> Dict[str, Any]:
    """ El repositorio entero (rama principal, sin historial) en <proyecto>/github_repos/<repo>/ """
    info = abrir(texto)
    url = f"{CODELOAD}/{info['ref']}/zip/refs/heads/{info['rama']}"
    try:
        r = requests.get(url, headers=_cabeceras(), stream=True, timeout=60)
    except requests.RequestException:
        raise ErrorGitHub("Sin conexión con GitHub: comprueba internet.")
    if r.status_code != 200:
        r.close()
        raise ErrorGitHub(f"GitHub respondió {r.status_code} al descargar el repositorio.")
    buf = io.BytesIO()
    ultimo = 0.0
    try:
        for trozo in r.iter_content(1 << 16):
            if cancelar is not None and cancelar.is_set():
                raise ErrorGitHub("Descarga cancelada.")
            buf.write(trozo)
            if buf.tell() > 2 << 30:
                raise ErrorGitHub("El repositorio pesa más de 2 GB: descárgalo con git.")
            if time.time() - ultimo > 0.4:
                ultimo = time.time()
                avisar({"tipo": "progreso", "bytes": buf.tell(), "mensaje": f"Descargando {buf.tell() / 1048576:.1f} MB"})
    finally:
        r.close()
    avisar({"tipo": "progreso", "bytes": buf.tell(), "mensaje": "Descomprimiendo…"})
    destino = carpeta_local(info["ref"], workspace)
    if os.path.isdir(destino):
        shutil.rmtree(destino)
    os.makedirs(destino)
    raiz = os.path.realpath(destino)
    with zipfile.ZipFile(buf) as z:
        for entrada in z.infolist():
            # El zip trae una carpeta «repo-rama/» delante de todo: se quita
            relativa = entrada.filename.split("/", 1)[1] if "/" in entrada.filename else ""
            if not relativa:
                continue
            ruta = os.path.realpath(os.path.join(destino, relativa))
            if not ruta.startswith(raiz + os.sep):
                continue
            if entrada.is_dir():
                os.makedirs(ruta, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(ruta), exist_ok=True)
            with z.open(entrada) as origen, open(ruta, "wb") as f:
                shutil.copyfileobj(origen, f)
    return local(info["ref"], workspace)


# ===========================================================================
# Exportar: explicación en Markdown y «código explicado» en PDF
# ===========================================================================

def exportar_markdown(texto: str, workspace: str) -> Dict[str, Any]:
    info = abrir(texto)
    e = explicadas(info)
    if not e["repo"] and not e["archivos"]:
        raise ErrorGitHub("Todavía no hay explicaciones de este repositorio: pide la del repositorio o la de algún archivo.")
    partes = [f"# {info['ref']}\n", f"{info.get('descripcion') or ''}\n", f"<{info['url']}> · ⭐ {info.get('estrellas')} · "
              f"{info.get('lenguaje') or ''} · licencia {info.get('licencia') or 'sin indicar'}\n"]
    if e["repo"]:
        partes += ["\n# El repositorio en conjunto\n", e["repo"]["texto"], "\n"]
    for ruta in sorted(e["archivos"]):
        partes += [f"\n# `{ruta}`\n", e["archivos"][ruta]["texto"], "\n"]
    partes.append(f"\n---\nExplicado con Prig el {datetime.now().strftime('%d/%m/%Y')}. Las explicaciones las generó un modelo de IA: pueden contener errores.\n")
    destino = os.path.join(workspace, CARPETA_EXPORT, info["ref"].replace("/", "__") + ".md")
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, "w", encoding="utf-8") as f:
        f.write("\n".join(partes))
    return {"ruta": destino, "relativa": os.path.relpath(destino, workspace), "archivos": len(e["archivos"]),
            "con_resumen": bool(e["repo"]), "bytes": os.path.getsize(destino)}


def exportar_pdf(texto: str, workspace: str) -> Dict[str, Any]:
    """ Resumen del repositorio y, por cada archivo explicado, su código con la explicación debajo """
    import kaggle_pdf as kp
    from reportlab.platypus import PageBreak, Paragraph, Spacer
    from html import escape
    info = abrir(texto)
    e = explicadas(info)
    if not e["repo"] and not e["archivos"]:
        raise ErrorGitHub("Todavía no hay explicaciones de este repositorio: pide la del repositorio o la de algún archivo.")
    kp._registrar_fuentes()
    est = kp._estilos()
    lineas = [f"de <b>{escape(info.get('dueno') or '')}</b> · {info.get('estrellas')} estrellas · {escape(info.get('lenguaje') or '')}",
              f'<link href="{escape(info["url"])}" color="#0a7bb0">{escape(info["url"])}</link>',
              f"{len(e['archivos'])} archivos explicados"]
    historia = kp._portada(info["ref"], est, "REPOSITORIO DE GITHUB EXPLICADO", lineas)
    historia.append(Spacer(1, 20))
    historia.append(Paragraph(escape(info.get("descripcion") or ""), est["portada_sub"]))
    historia.append(Paragraph(f"Licencia del código original: {escape(info.get('licencia') or 'sin indicar')}. "
                              "Las explicaciones las generó un modelo de IA: pueden contener errores.", est["nota"]))
    if e["repo"]:
        historia += [PageBreak(), Paragraph("El repositorio en conjunto", est["seccion"]),
                     kp._caja_profesor(e["repo"]["texto"], est, "PROFESOR · VISIÓN GENERAL")]
    for ruta in sorted(e["archivos"]):
        historia.append(PageBreak())
        historia.append(Paragraph(escape(ruta), est["seccion"]))
        try:
            a = leer_archivo(info["ref"], ruta)
            codigo = a.get("contenido") or ""
        except ErrorGitHub:
            codigo = ""
        if codigo:
            recortado = codigo.count("\n") > 400
            historia += kp._caja_codigo("\n".join(codigo.split("\n")[:400]), est, lenguaje=_lenguaje(ruta) if _lenguaje(ruta) != "plaintext" else "text")
            if recortado:
                historia.append(Paragraph("… (el archivo sigue: se muestran las primeras 400 líneas)", est["nota"]))
        historia.append(Spacer(1, 6))
        nivel = e["archivos"][ruta].get("nivel") or ""
        historia.append(kp._caja_profesor(e["archivos"][ruta]["texto"], est, f"PROFESOR{' · NIVEL ' + nivel.upper() if nivel else ''}"))
    destino = os.path.join(workspace, CARPETA_EXPORT, info["ref"].replace("/", "__") + ".pdf")
    paginas = kp._construir(destino, historia, info["ref"])
    return {"ruta": destino, "relativa": os.path.relpath(destino, workspace), "paginas": paginas,
            "archivos": len(e["archivos"]), "con_resumen": bool(e["repo"]), "bytes": os.path.getsize(destino)}
