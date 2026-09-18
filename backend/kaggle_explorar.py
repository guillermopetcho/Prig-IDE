"""
Explorar Kaggle como en su web: datasets y competiciones, sus archivos y sus datos.

Medido contra la API oficial (https://www.kaggle.com/api/v1):

    datasets/list                 buscar              funciona SIN cuenta
    datasets/view/{dueño}/{slug}  ficha completa      sin cuenta (descripción en markdown, etiquetas…)
    datasets/list/{dueño}/{slug}  sus archivos        sin cuenta
    datasets/download/{…}         zip con todo        sin cuenta
    competitions/list             buscar              con cuenta
    competitions/data/list/{c}    sus archivos        con cuenta
    competitions/data/download-all/{c}   zip          con cuenta y reglas aceptadas

Filtros válidos (probados uno a uno): datasets sortBy = hottest, votes, updated, active,
published; filetype = csv, json, sqlite, bigQuery, parquet. Competiciones: category =
featured, research, gettingStarted, playground, community (el valor «all» da 400: sin
categoría ya devuelve las activas); sortBy = grouped, prize, earliestDeadline,
latestDeadline, numberOfTeams, recentlyCreated.

Kaggle NO devuelve las salidas de los notebooks (ni en «pull» ni en «output»), así que
la forma de ver sus tablas y gráficos es bajar los datos y ejecutarlo en Prig: los datos
van a <proyecto>/kaggle_datos/<slug>/, que es lo que Kaggle monta en /kaggle/input/<slug>/,
y al guardar un notebook en el proyecto esas rutas se reescriben para que funcione tal cual.

Las respuestas de la API traen cada campo repetido («title», «titleNullable», «hasTitle»):
aquí se normalizan a unos pocos campos en castellano.
"""

import csv
import hashlib
import json
import os
import re
import shutil
import threading
import time
import zipfile
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import requests

import kaggle_lector as kl
from kaggle_lector import ErrorKaggle

ORDEN_DATASETS = {"populares": "hottest", "votos": "votes", "recientes": "updated", "activos": "active", "nuevos": "published"}
TIPOS_ARCHIVO = {"csv", "json", "sqlite", "bigQuery", "parquet"}
LICENCIAS = {"cc": "Creative Commons", "gpl": "GPL", "odb": "Open Database", "other": "Otras"}
TAMANOS = {"pequeno": (None, 1 << 20), "mediano": (1 << 20, 100 << 20), "grande": (100 << 20, 1 << 30), "enorme": (1 << 30, None)}
GRUPOS = {"general": "general", "mias": "entered"}
CATEGORIAS = {"featured": "Destacadas", "gettingStarted": "Para empezar", "playground": "Playground",
              "research": "Investigación", "community": "Comunidad"}
ORDEN_COMPETICIONES = {"agrupadas": "grouped", "premio": "prize", "cierre": "earliestDeadline",
                       "equipos": "numberOfTeams", "nuevas": "recentlyCreated"}
SLUG = re.compile(r"^[A-Za-z0-9_\-.]{1,120}$")
LIMITE_PREVIA = 20000          # filas que se leen para las estadísticas de una tabla
CARPETA_DATOS = "kaggle_datos"

_cache: Dict[str, Any] = {}
_cerrojo = threading.Lock()


def _cacheado(clave: str, segundos: float, fn: Callable[[], Any]) -> Any:
    guardado = _cache.get(clave)
    if guardado and time.time() - guardado[0] < segundos:
        return guardado[1]
    valor = fn()
    _cache[clave] = (time.time(), valor)
    return valor


def _etiquetas(d: Dict[str, Any]) -> List[str]:
    return [t.get("name") for t in d.get("tags") or [] if t.get("name")][:12]


# ===========================================================================
# Referencias
# ===========================================================================

def ref_dataset(texto: str) -> str:
    t = (texto or "").strip()
    m = re.search(r"kaggle\.com/datasets/([A-Za-z0-9_\-]+)/([A-Za-z0-9_\-.]+)", t)
    ref = f"{m.group(1)}/{m.group(2)}" if m else t.strip("/")
    ref = re.sub(r"/(?:data|code|discussion|versions/\d+|suggestions)$", "", ref)
    if not kl.REF_VALIDA.match(ref) or ".." in ref:
        raise ErrorKaggle("Eso no es un dataset de Kaggle: pega un enlace como kaggle.com/datasets/usuario/nombre.")
    return ref


def ref_competicion(texto: str) -> str:
    t = (texto or "").strip()
    m = re.search(r"kaggle\.com/(?:competitions|c)/([A-Za-z0-9_\-.]+)", t)
    slug = m.group(1) if m else t.strip("/")
    if not SLUG.match(slug) or ".." in slug:
        raise ErrorKaggle("Eso no es una competición de Kaggle: pega un enlace como kaggle.com/competitions/titanic.")
    return slug


# ===========================================================================
# Datasets
# ===========================================================================

def _dataset_corto(d: Dict[str, Any]) -> Dict[str, Any]:
    return {"ref": d.get("ref"), "titulo": d.get("title"), "subtitulo": d.get("subtitle") or "",
            "autor": d.get("ownerName") or d.get("creatorName"), "imagen": d.get("thumbnailImageUrl"),
            "votos": d.get("voteCount"), "descargas": d.get("downloadCount"), "vistas": d.get("viewCount"),
            "bytes": d.get("totalBytes"), "usabilidad": round(float(d.get("usabilityRating") or 0) * 10, 1),
            "actualizado": d.get("lastUpdated"), "licencia": d.get("licenseName"),
            "notebooks": d.get("kernelCount"), "etiquetas": _etiquetas(d),
            "url": d.get("url") or f"https://www.kaggle.com/datasets/{d.get('ref')}"}


def buscar_datasets(consulta: str = "", orden: str = "populares", pagina: int = 1, tipo_archivo: str = "",
                    licencia: str = "", tamano: str = "", usuario: str = "") -> Dict[str, Any]:
    """ Filtros medidos que Kaggle respeta: filetype, license (cc, gpl, odb, other),
    minSize/maxSize en bytes y user. «tagids» no filtra nada, así que no se ofrece. """
    params: Dict[str, Any] = {"page": max(1, int(pagina)), "sortBy": ORDEN_DATASETS.get(orden, "hottest")}
    if consulta.strip():
        params["search"] = consulta.strip()[:100]
    if tipo_archivo in TIPOS_ARCHIVO:
        params["filetype"] = tipo_archivo
    if licencia in LICENCIAS:
        params["license"] = licencia
    if tamano in TAMANOS:
        minimo, maximo = TAMANOS[tamano]
        if minimo:
            params["minSize"] = minimo
        if maximo:
            params["maxSize"] = maximo
    if usuario.strip():
        params["user"] = usuario.strip()[:60]

    def pedir():
        datos = kl._pedir("datasets/list", params, obligar_cuenta=False)
        lista = datos if isinstance(datos, list) else []
        return {"datasets": [_dataset_corto(d) for d in lista if d.get("ref")], "pagina": params["page"],
                "hay_mas": len(lista) >= 20}
    return _cacheado("dl:" + json.dumps(params, sort_keys=True), 600, pedir)


def _archivos_dataset(ref: str) -> List[Dict[str, Any]]:
    archivos, token = [], None
    for _ in range(10):                         # hasta 10 páginas: datasets con miles de archivos
        params = {"pageToken": token} if token else {}
        d = kl._pedir(f"datasets/list/{ref}", params, obligar_cuenta=False)
        for f in d.get("datasetFiles") or []:
            archivos.append({"nombre": f.get("name"), "bytes": f.get("totalBytes"),
                             "descripcion": f.get("description") or "",
                             "columnas": [{"nombre": c.get("name"), "tipo": c.get("type"), "descripcion": c.get("description") or ""}
                                          for c in f.get("columns") or []][:80]})
        token = d.get("nextPageToken")
        if not token:
            break
    return archivos


def dataset(texto: str, workspace: Optional[str] = None) -> Dict[str, Any]:
    ref = ref_dataset(texto)

    def pedir():
        d = kl._pedir(f"datasets/view/{ref}", {}, obligar_cuenta=False)
        ficha = _dataset_corto(d)
        ficha.update(descripcion=d.get("description") or "", version=d.get("currentVersionNumber"),
                     archivos=_archivos_dataset(ref),
                     versiones=[{"numero": v.get("versionNumber"), "fecha": v.get("creationDate"), "notas": v.get("versionNotes")}
                                for v in (d.get("versions") or [])[:10]])
        return ficha
    ficha = dict(_cacheado("dv:" + ref, 3600, pedir))
    ficha["tipo"] = "dataset"
    ficha["local"] = local("dataset", ref, workspace) if workspace else None
    return ficha


# ===========================================================================
# Competiciones
# ===========================================================================

def _competicion_corta(c: Dict[str, Any]) -> Dict[str, Any]:
    url = c.get("url") or c.get("ref") or ""
    slug = url.rstrip("/").split("/")[-1]
    fin = c.get("deadline")
    return {"ref": slug, "titulo": c.get("title"), "subtitulo": c.get("description") or "",
            "organizador": c.get("organizationName") or c.get("hostName"), "imagen": c.get("thumbnailImageUrl"),
            "categoria": c.get("category"), "premio": c.get("reward"), "equipos": c.get("teamCount"),
            "cierre": fin, "abierta": bool(fin and fin > datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")),
            "metrica": c.get("evaluationMetric"), "max_equipo": c.get("maxTeamSize"),
            "envios_diarios": c.get("maxDailySubmissions"), "inscrito": bool(c.get("userHasEntered")),
            "solo_notebooks": bool(c.get("isKernelsSubmissionsOnly")), "etiquetas": _etiquetas(c),
            "url": url or f"https://www.kaggle.com/competitions/{slug}"}


def buscar_competiciones(consulta: str = "", categoria: str = "", orden: str = "agrupadas", pagina: int = 1,
                         grupo: str = "") -> Dict[str, Any]:
    """ «group=entered» son las competiciones en las que participa el usuario (medido;
    «inClass» da 400) """
    params: Dict[str, Any] = {"page": max(1, int(pagina)), "sortBy": ORDEN_COMPETICIONES.get(orden, "grouped")}
    if grupo in GRUPOS and grupo != "general":
        params["group"] = GRUPOS[grupo]
    if consulta.strip():
        params["search"] = consulta.strip()[:100]
    if categoria in CATEGORIAS:
        params["category"] = categoria

    def pedir():
        datos = kl._pedir("competitions/list", params)
        lista = datos if isinstance(datos, list) else []
        return {"competiciones": [_competicion_corta(c) for c in lista], "pagina": params["page"], "hay_mas": len(lista) >= 19}
    return _cacheado("cl:" + json.dumps(params, sort_keys=True), 600, pedir)


def competicion(texto: str, workspace: Optional[str] = None) -> Dict[str, Any]:
    slug = ref_competicion(texto)

    def pedir():
        # No hay «view» de competiciones en la API: se busca por su nombre y se toma la que coincide
        lista = kl._pedir("competitions/list", {"search": slug.replace("-", " ")[:100]})
        ficha = next((_competicion_corta(c) for c in lista or [] if _competicion_corta(c)["ref"] == slug), None)
        if ficha is None:
            lista = kl._pedir("competitions/list", {"search": slug})
            ficha = next((_competicion_corta(c) for c in lista or [] if _competicion_corta(c)["ref"] == slug), None)
        if ficha is None:
            ficha = {"ref": slug, "titulo": slug, "subtitulo": "", "url": f"https://www.kaggle.com/competitions/{slug}", "etiquetas": []}
        d = kl._pedir(f"competitions/data/list/{slug}", {})
        ficha["archivos"] = [{"nombre": f.get("name"), "bytes": f.get("totalBytes"), "descripcion": f.get("description") or "", "columnas": []}
                             for f in (d.get("files") if isinstance(d, dict) else d) or []]
        ficha["bytes"] = sum(f["bytes"] or 0 for f in ficha["archivos"])
        ficha["reglas"] = f"https://www.kaggle.com/competitions/{slug}/rules"
        return ficha
    ficha = dict(_cacheado("cv:" + slug, 3600, pedir))
    ficha["tipo"] = "competicion"
    ficha["local"] = local("competicion", slug, workspace) if workspace else None
    return ficha


# ===========================================================================
# Datos en el proyecto
# ===========================================================================

def _nombre_local(tipo: str, ref: str) -> str:
    """ Igual que el punto de montaje de Kaggle: /kaggle/input/<slug> """
    return ref.split("/")[-1]


def carpeta_local(tipo: str, ref: str, workspace: str) -> str:
    return os.path.join(workspace, CARPETA_DATOS, _nombre_local(tipo, ref))


def local(tipo: str, ref: str, workspace: str) -> Optional[Dict[str, Any]]:
    """ Qué hay ya descargado en el proyecto """
    raiz = carpeta_local(tipo, ref, workspace)
    if not os.path.isdir(raiz):
        return None
    archivos = []
    for base, _, nombres in os.walk(raiz):
        for n in sorted(nombres):
            ruta = os.path.join(base, n)
            archivos.append({"ruta": ruta, "relativa": os.path.relpath(ruta, raiz), "bytes": os.path.getsize(ruta)})
            if len(archivos) >= 500:
                break
    return {"carpeta": raiz, "relativa": os.path.relpath(raiz, workspace), "archivos": archivos,
            "bytes": sum(a["bytes"] for a in archivos)}


def _url_descarga(tipo: str, ref: str) -> str:
    return (f"{kl.API}/datasets/download/{ref}" if tipo == "dataset"
            else f"{kl.API}/competitions/data/download-all/{ref}")


def descargar(tipo: str, texto: str, workspace: str, avisar: Callable[[Dict[str, Any]], None] = lambda e: None,
              cancelar: Optional[threading.Event] = None) -> Dict[str, Any]:
    """ Baja el zip con todos los archivos y lo descomprime en kaggle_datos/<slug>/ """
    ref = ref_dataset(texto) if tipo == "dataset" else ref_competicion(texto)
    c = kl.credenciales()
    if tipo != "dataset" and not c:
        raise ErrorKaggle("Para bajar los datos de una competición hace falta conectar tu cuenta de Kaggle.")
    auth, cab = kl._auth(c)
    destino = carpeta_local(tipo, ref, workspace)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    zip_tmp = destino + ".zip.parcial"
    try:
        r = requests.get(_url_descarga(tipo, ref), auth=auth, headers={**kl.UA, **cab}, stream=True, timeout=60)
    except requests.RequestException:
        raise ErrorKaggle("Sin conexión con Kaggle: comprueba internet.")
    try:
        if r.status_code == 403 and tipo != "dataset":
            raise ErrorKaggle(f"Kaggle pide aceptar las reglas de la competición antes de bajar sus datos: "
                              f"entra en kaggle.com/competitions/{ref}/rules, pulsa «I Understand and Accept» y reintenta.")
        if r.status_code == 401:
            raise ErrorKaggle("Kaggle no aceptó tus credenciales: vuelve a conectar la cuenta.")
        if r.status_code == 404:
            raise ErrorKaggle("Kaggle no encuentra esos datos (¿privados o borrados?).")
        if r.status_code != 200:
            raise ErrorKaggle(f"Kaggle respondió {r.status_code} al descargar.")
        total = int(r.headers.get("content-length") or 0)
        bajado, ultimo = 0, 0.0
        with open(zip_tmp, "wb") as f:
            for trozo in r.iter_content(1 << 16):
                if cancelar is not None and cancelar.is_set():
                    raise ErrorKaggle("Descarga cancelada.")
                f.write(trozo)
                bajado += len(trozo)
                if time.time() - ultimo > 0.4:
                    ultimo = time.time()
                    avisar({"tipo": "progreso", "bytes": bajado, "total": total,
                            "mensaje": f"Descargando {_tam(bajado)}" + (f" de {_tam(total)}" if total else "")})
    except BaseException:
        try:
            os.remove(zip_tmp)
        except OSError:
            pass
        raise
    finally:
        r.close()
    avisar({"tipo": "progreso", "bytes": bajado, "total": total, "mensaje": "Descomprimiendo…"})
    try:
        _descomprimir(zip_tmp, destino)
    finally:
        try:
            os.remove(zip_tmp)
        except OSError:
            pass
    _registrar(tipo, ref, destino)
    return local(tipo, ref, workspace)


def _ruta_registro() -> str:
    return os.path.join(kl.carpeta(), "descargas.json")


def _registrar(tipo: str, ref: str, carpeta: str):
    with _cerrojo:
        datos = kl._leer_json(_ruta_registro()) or {}
        datos[carpeta] = {"tipo": tipo, "ref": ref, "fecha": datetime.now().isoformat(timespec="seconds")}
        os.makedirs(kl.carpeta(), exist_ok=True)
        with open(_ruta_registro() + ".tmp", "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False)
        os.replace(_ruta_registro() + ".tmp", _ruta_registro())


def mis_datos(workspace: str) -> List[Dict[str, Any]]:
    """ Lo descargado en el proyecto abierto, lo más reciente primero """
    registro = kl._leer_json(_ruta_registro()) or {}
    raiz = os.path.join(workspace, CARPETA_DATOS)
    salida = []
    for nombre in sorted(os.listdir(raiz)) if os.path.isdir(raiz) else []:
        carpeta = os.path.join(raiz, nombre)
        if not os.path.isdir(carpeta):
            continue
        r = registro.get(carpeta) or {}
        tipo, ref = r.get("tipo"), r.get("ref") or nombre
        info = local(tipo or "dataset", ref, workspace) if tipo else None
        if info is None:
            archivos = [os.path.join(b, n) for b, _, ns in os.walk(carpeta) for n in ns]
            info = {"carpeta": carpeta, "relativa": os.path.relpath(carpeta, workspace), "bytes": sum(os.path.getsize(a) for a in archivos),
                    "archivos": [{"ruta": a, "relativa": os.path.relpath(a, carpeta), "bytes": os.path.getsize(a)} for a in archivos[:500]]}
        salida.append({"nombre": nombre, "tipo": tipo, "ref": ref, "fecha": r.get("fecha"), **info})
    return sorted(salida, key=lambda x: x.get("fecha") or "", reverse=True)


def _descomprimir(zip_ruta: str, destino: str):
    try:
        z = zipfile.ZipFile(zip_ruta)
    except zipfile.BadZipFile:
        # Algunos datasets de un solo archivo llegan sin comprimir
        os.makedirs(destino, exist_ok=True)
        shutil.move(zip_ruta, os.path.join(destino, "datos"))
        return
    raiz = os.path.realpath(destino)
    os.makedirs(destino, exist_ok=True)
    with z:
        for info in z.infolist():
            ruta = os.path.realpath(os.path.join(destino, info.filename))
            if not (ruta == raiz or ruta.startswith(raiz + os.sep)):
                continue                      # «zip slip»: nada fuera de la carpeta
            if info.is_dir():
                os.makedirs(ruta, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(ruta), exist_ok=True)
            with z.open(info) as origen, open(ruta, "wb") as f:
                shutil.copyfileobj(origen, f)


def _tam(n: float) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024
    return f"{n} B"


# ===========================================================================
# Vista previa de una tabla
# ===========================================================================

def _numero(v: str) -> Optional[float]:
    try:
        return float(v.replace(",", "")) if v not in ("", "NA", "NaN", "nan", "null", "None") else None
    except ValueError:
        return None


VACIOS = {"", "NA", "N/A", "NaN", "nan", "null", "NULL", "None"}


def vista_previa(ruta: str, workspace: str, filas: int = 15) -> Dict[str, Any]:
    """ Primeras filas y un resumen por columna, como el «Data Explorer» de Kaggle """
    raiz = os.path.realpath(os.path.join(workspace, CARPETA_DATOS))
    real = os.path.realpath(ruta)
    if not real.startswith(raiz + os.sep) or not os.path.isfile(real):
        raise ErrorKaggle("Ese archivo no está entre los datos descargados.")
    nombre = os.path.basename(real)
    ext = nombre.lower().rsplit(".", 1)[-1] if "." in nombre else ""
    base = {"nombre": nombre, "bytes": os.path.getsize(real), "tipo": ext}
    if ext in ("csv", "tsv"):
        return {**base, **_resumen_csv(real, "\t" if ext == "tsv" else None, filas)}
    if ext in ("json", "txt", "md", "geojson"):
        with open(real, encoding="utf-8", errors="replace") as f:
            return {**base, "texto": f.read(6000)}
    if ext in ("png", "jpg", "jpeg", "gif", "webp"):
        return {**base, "imagen": True}
    return {**base, "nota": "Sin vista previa para este tipo de archivo."}


def _resumen_csv(ruta: str, separador: Optional[str], filas: int) -> Dict[str, Any]:
    with open(ruta, newline="", encoding="utf-8", errors="replace") as f:
        muestra = f.read(20000)
        f.seek(0)
        if separador is None:
            try:
                separador = csv.Sniffer().sniff(muestra, delimiters=",;\t|").delimiter
            except csv.Error:
                separador = ","
        lector = csv.reader(f, delimiter=separador)
        cabecera = next(lector, [])
        primeras, leidas = [], 0
        cols = [{"nombre": c, "faltan": 0, "numeros": 0, "valores": {}, "min": None, "max": None, "suma": 0.0} for c in cabecera]
        for fila in lector:
            if leidas < filas:
                primeras.append(fila[:len(cabecera)])
            if leidas < LIMITE_PREVIA:
                for i, c in enumerate(cols):
                    v = fila[i].strip() if i < len(fila) else ""
                    if v in VACIOS:
                        c["faltan"] += 1
                        continue
                    n = _numero(v)
                    if n is not None:
                        c["numeros"] += 1
                        c["suma"] += n
                        c["min"] = n if c["min"] is None else min(c["min"], n)
                        c["max"] = n if c["max"] is None else max(c["max"], n)
                    if len(c["valores"]) <= 1000:
                        c["valores"][v] = c["valores"].get(v, 0) + 1
            leidas += 1
    analizadas = min(leidas, LIMITE_PREVIA)
    columnas = []
    for c in cols:
        presentes = analizadas - c["faltan"]
        numerica = presentes > 0 and c["numeros"] >= presentes * 0.95
        frecuentes = sorted(c["valores"].items(), key=lambda x: -x[1])[:5]
        columnas.append({
            "nombre": c["nombre"], "tipo": "número" if numerica else "texto",
            "faltan": c["faltan"], "faltan_pct": round(100 * c["faltan"] / analizadas, 1) if analizadas else 0,
            "distintos": len(c["valores"]) if len(c["valores"]) <= 1000 else "más de 1000",
            "min": c["min"] if numerica else None, "max": c["max"] if numerica else None,
            "media": round(c["suma"] / c["numeros"], 4) if numerica and c["numeros"] else None,
            # Ni en números continuos ni en columnas donde casi todo es distinto (nombres, ids)
            "frecuentes": [] if (numerica and len(c["valores"]) > 20) or (presentes > 20 and len(c["valores"]) > presentes * 0.9)
            else [{"valor": v[:60], "veces": n} for v, n in frecuentes],
        })
    return {"separador": separador, "columnas": columnas, "filas": primeras, "total_filas": leidas,
            "analizadas": analizadas}


# ===========================================================================
# El profesor explica los datos
# ===========================================================================

SISTEMA_DATOS = """Eres un científico de datos senior que presenta un conjunto de datos de Kaggle a un
alumno antes de trabajar con él. En español, claro y concreto, apoyándote SOLO en la
información que se te da (descripción, archivos, columnas, estadísticas y filas de ejemplo).
Usa exactamente estas secciones en markdown:

## Qué contiene
Qué representa cada fila y de dónde vienen los datos.
## Las columnas que importan
Las más relevantes, qué significan y de qué tipo son. Si hay una variable objetivo evidente, dila.
## Calidad de los datos
Valores faltantes, columnas raras, desequilibrios o cosas a limpiar, citando las cifras.
## Qué se puede hacer con ellos
3-5 ideas concretas de análisis o modelos, de la más sencilla a la más ambiciosa.
## Por dónde empezar
Un bloque corto de código Python (pandas) para cargarlo y echar el primer vistazo,
con la ruta que se te indica.

No inventes columnas ni cifras que no aparezcan."""


def contexto_datos(ficha: Dict[str, Any], previas: List[Dict[str, Any]]) -> str:
    partes = [f"{'DATASET' if ficha.get('tipo') == 'dataset' else 'COMPETICIÓN'}: «{ficha.get('titulo')}»",
              f"Subtítulo: {ficha.get('subtitulo') or '-'}", f"Etiquetas: {', '.join(ficha.get('etiquetas') or []) or '-'}"]
    if ficha.get("metrica"):
        partes.append(f"Métrica de evaluación: {ficha['metrica']}")
    if ficha.get("descripcion"):
        partes.append("DESCRIPCIÓN:\n" + re.sub(r"!\[[^\]]*\]\([^)]*\)", "", ficha["descripcion"])[:3500])
    partes.append("ARCHIVOS:\n" + "\n".join(f"- {a['nombre']} ({_tam(a['bytes'] or 0)})" for a in (ficha.get("archivos") or [])[:30]))
    for p in previas[:3]:
        cols = "\n".join(
            f"  · {c['nombre']} [{c['tipo']}] faltan {c['faltan_pct']}% · distintos {c['distintos']}"
            + (f" · min {c['min']} máx {c['max']} media {c['media']}" if c["tipo"] == "número" else "")
            + (f" · frecuentes: {', '.join(f['valor'] for f in c['frecuentes'][:4])}" if c.get("frecuentes") else "")
            for c in p.get("columnas", [])[:40])
        ejemplo = "\n".join(",".join(f) for f in p.get("filas", [])[:5])
        partes.append(f"TABLA {p['nombre']} — {p.get('total_filas')} filas, {len(p.get('columnas', []))} columnas "
                      f"(ruta en el proyecto: {p.get('ruta_relativa', p['nombre'])})\n{cols}\nPRIMERAS FILAS:\n{ejemplo}")
    return "\n\n".join(partes)[:14000]


def previas_para_modelo(ficha: Dict[str, Any], workspace: str) -> List[Dict[str, Any]]:
    """ Resumen de las tablas descargadas (las 3 mayores), si las hay """
    loc = ficha.get("local") or {}
    tablas = sorted([a for a in loc.get("archivos") or [] if a["relativa"].lower().endswith((".csv", ".tsv"))],
                    key=lambda a: -a["bytes"])[:3]
    previas = []
    for a in tablas:
        try:
            p = vista_previa(a["ruta"], workspace, filas=5)
            p["ruta_relativa"] = os.path.relpath(a["ruta"], workspace)
            previas.append(p)
        except (ErrorKaggle, OSError, csv.Error):
            continue
    return previas


def explicar_datos(ai, modelo: str, ficha: Dict[str, Any], workspace: str):
    from desafios.tutor import flujo
    return (yield from flujo(ai, modelo, contexto_datos(ficha, previas_para_modelo(ficha, workspace)),
                             SISTEMA_DATOS, temperatura=0.3))


def _ruta_explicacion_datos(tipo: str, ref: str) -> str:
    return os.path.join(kl.carpeta(), "explicaciones", f"datos__{tipo}__{ref.replace('/', '__')}.json")


def explicacion_datos(tipo: str, ref: str, modelo: str, huella: str) -> Optional[str]:
    return ((kl._leer_json(_ruta_explicacion_datos(tipo, ref)) or {}).get(f"{modelo}:{huella}") or {}).get("texto")


def guardar_explicacion_datos(tipo: str, ref: str, modelo: str, huella: str, texto: str):
    ruta = _ruta_explicacion_datos(tipo, ref)
    with _cerrojo:
        datos = kl._leer_json(ruta) or {}
        datos[f"{modelo}:{huella}"] = {"texto": texto, "fecha": datetime.now().isoformat(timespec="seconds")}
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta + ".tmp", "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False)
        os.replace(ruta + ".tmp", ruta)


def huella(ficha: Dict[str, Any]) -> str:
    """ Cambia si se bajan los datos: la explicación con estadísticas reales es otra """
    loc = ficha.get("local") or {}
    return hashlib.sha1(f"{ficha.get('version')}:{bool(loc)}:{loc.get('bytes')}".encode()).hexdigest()[:10]


# ===========================================================================
# Notebooks que funcionan en el proyecto
# ===========================================================================

def reescribir_rutas(fuente: str, workspace: str) -> str:
    """ /kaggle/input/<slug>/… y ../input/<slug>/… → <proyecto>/kaggle_datos/<slug>/… """
    local_datos = os.path.join(workspace, CARPETA_DATOS).replace("\\", "/") + "/"
    fuente = fuente.replace("/kaggle/input/", local_datos)
    return re.sub(r"(?<![\w/])\.\./input/", local_datos, fuente)


def datos_del_notebook(nb: Dict[str, Any], workspace: str) -> List[Dict[str, Any]]:
    """ Cada fuente de datos del notebook y si ya está en el proyecto """
    fuentes = [("competicion", c) for c in nb.get("competiciones") or []] + [("dataset", d) for d in nb.get("datasets") or []]
    return [{"tipo": t, "ref": r, "descargado": local(t, r, workspace) is not None} for t, r in fuentes]
