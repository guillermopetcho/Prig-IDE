"""
Leer notebooks de la comunidad de Kaggle con un modelo al lado.

Con la API oficial de Kaggle (https://www.kaggle.com/api/v1), medida al hacerlo:

    kernels/list   buscar notebooks        necesita cuenta (sin ella responde 401)
    kernels/pull   el notebook completo    funciona sin cuenta para los públicos

Credenciales, en el mismo orden que el cliente oficial (kaggle-cli):
    1. las que se guardan desde Prig (~/.prig_kaggle.json, permisos 600)
    2. token nuevo: KAGGLE_API_TOKEN o ~/.kaggle/access_token    → Authorization: Bearer
    3. clave antigua: KAGGLE_USERNAME + KAGGLE_KEY o kaggle.json    → autenticación básica
       (en $KAGGLE_CONFIG_DIR, ~/.kaggle o ~/.config/kaggle)
Nunca se devuelven al navegador: solo el usuario y de dónde salieron.

El notebook se guarda en disco (~/.prig_kaggle/notebooks) para leerlo sin red, y cada
explicación del modelo también, para no pagarla dos veces. Kaggle no incluye las
salidas de las celdas en «pull»: se leen el código y el texto, no los resultados.
"""

import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

API = "https://www.kaggle.com/api/v1"
UA = {"User-Agent": "Prig-IDE (lector de notebooks; uso educativo local)"}
ORDENES = {"relevancia": "relevance", "votos": "voteCount", "populares": "hotness", "recientes": "dateRun",
           "comentados": "commentCount", "vistos": "viewCount", "nuevos": "dateCreated"}
REF_VALIDA = re.compile(r"^[A-Za-z0-9_\-]{1,60}/[A-Za-z0-9_\-.]{1,120}$")


class ErrorKaggle(Exception):
    pass


def carpeta() -> str:
    return os.environ.get("PRIG_KAGGLE_DIR") or os.path.expanduser("~/.prig_kaggle")


def ruta_credenciales_prig() -> str:
    return os.environ.get("PRIG_KAGGLE_CREDENCIALES") or os.path.expanduser("~/.prig_kaggle.json")


# ===========================================================================
# Credenciales
# ===========================================================================

def _leer_json(ruta: str) -> Optional[Dict[str, Any]]:
    try:
        with open(ruta, encoding="utf-8") as f:
            datos = json.load(f)
        return datos if isinstance(datos, dict) else None
    except (OSError, ValueError):
        return None


def _leer_texto(ruta: str) -> Optional[str]:
    try:
        with open(ruta, encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def _dirs_config() -> List[str]:
    dirs = []
    if os.environ.get("KAGGLE_CONFIG_DIR"):
        dirs.append(os.environ["KAGGLE_CONFIG_DIR"])
    dirs.append(os.path.expanduser("~/.kaggle"))
    dirs.append(os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "kaggle"))
    return dirs


def credenciales() -> Optional[Dict[str, Any]]:
    """ {"tipo": "token"|"clave", "token"|("usuario","clave"), "origen": texto legible} o None """
    prig = _leer_json(ruta_credenciales_prig())
    if prig:
        if prig.get("token"):
            return {"tipo": "token", "token": prig["token"], "usuario": prig.get("usuario"), "origen": "Prig"}
        if prig.get("username") and prig.get("key"):
            return {"tipo": "clave", "usuario": prig["username"], "clave": prig["key"], "origen": "Prig"}
    if os.environ.get("KAGGLE_API_TOKEN"):
        return {"tipo": "token", "token": os.environ["KAGGLE_API_TOKEN"], "usuario": None, "origen": "variable KAGGLE_API_TOKEN"}
    for d in _dirs_config():
        token = _leer_texto(os.path.join(d, "access_token"))
        if token:
            return {"tipo": "token", "token": token, "usuario": None, "origen": os.path.join(d, "access_token").replace(os.path.expanduser("~"), "~")}
    if os.environ.get("KAGGLE_USERNAME") and os.environ.get("KAGGLE_KEY"):
        return {"tipo": "clave", "usuario": os.environ["KAGGLE_USERNAME"], "clave": os.environ["KAGGLE_KEY"],
                "origen": "variables KAGGLE_USERNAME y KAGGLE_KEY"}
    for d in _dirs_config():
        datos = _leer_json(os.path.join(d, "kaggle.json"))
        if datos and datos.get("username") and datos.get("key"):
            return {"tipo": "clave", "usuario": datos["username"], "clave": datos["key"],
                    "origen": os.path.join(d, "kaggle.json").replace(os.path.expanduser("~"), "~")}
    return None


def _auth(c: Optional[Dict[str, Any]]):
    """ (auth, cabeceras) para requests """
    if not c:
        return None, {}
    if c["tipo"] == "token":
        return None, {"Authorization": f"Bearer {c['token']}"}
    return (c["usuario"], c["clave"]), {}


def estado() -> Dict[str, Any]:
    c = credenciales()
    return {"conectado": bool(c), "usuario": (c or {}).get("usuario"), "origen": (c or {}).get("origen"),
            "metodo": (c or {}).get("tipo"),
            "url_token": "https://www.kaggle.com/settings/account",
            "nota": "Sin cuenta puedes abrir cualquier notebook público pegando su enlace; para buscar hace falta conectar Kaggle."}


def guardar_credenciales(texto: str) -> Dict[str, Any]:
    """ Acepta el contenido de kaggle.json o un token de API. Se comprueba con Kaggle antes de guardarlo. """
    t = (texto or "").strip().strip("\"'`")
    if not t:
        raise ErrorKaggle("Pega el contenido de kaggle.json o tu token de API de Kaggle.")
    nuevo: Dict[str, Any]
    if t.startswith("{"):
        try:
            datos = json.loads(t)
        except ValueError:
            raise ErrorKaggle("Eso parece un kaggle.json pero no se puede leer: cópialo entero, con las llaves.")
        if not (datos.get("username") and datos.get("key")):
            raise ErrorKaggle("El kaggle.json debe tener «username» y «key».")
        nuevo = {"username": str(datos["username"]), "key": str(datos["key"])}
        c = {"tipo": "clave", "usuario": nuevo["username"], "clave": nuevo["key"]}
    else:
        if re.search(r"\s", t) or len(t) < 20:
            raise ErrorKaggle("El token tiene espacios o es demasiado corto: cópialo con el botón de Kaggle.")
        nuevo = {"token": t}
        c = {"tipo": "token", "token": t}
    _pedir("kernels/list", {"pageSize": 1, "search": "titanic"}, c)       # falla con 401 si no vale
    ruta = ruta_credenciales_prig()
    fd = os.open(ruta + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({**nuevo, "guardado": datetime.now().isoformat(timespec="seconds")}, f)
    os.replace(ruta + ".tmp", ruta)
    os.chmod(ruta, 0o600)
    return estado()


def borrar_credenciales() -> Dict[str, Any]:
    try:
        os.remove(ruta_credenciales_prig())
    except FileNotFoundError:
        pass
    return estado()


# ===========================================================================
# API
# ===========================================================================

def _pedir(ruta: str, params: Dict[str, Any], c: Optional[Dict[str, Any]] = None, obligar_cuenta: bool = True):
    c = c if c is not None else credenciales()
    if obligar_cuenta and not c:
        raise ErrorKaggle("Para buscar en Kaggle hace falta conectar tu cuenta. Sin ella puedes abrir un notebook pegando su enlace.")
    auth, cab = _auth(c)
    try:
        r = requests.get(f"{API}/{ruta}", params=params, auth=auth, headers={**UA, **cab}, timeout=30)
    except requests.RequestException:
        raise ErrorKaggle("Sin conexión con Kaggle: comprueba internet.")
    if r.status_code == 401:
        raise ErrorKaggle("Kaggle no aceptó tus credenciales: crea un token nuevo en kaggle.com → Settings → API y vuelve a conectar.")
    if r.status_code == 403:
        raise ErrorKaggle("Kaggle no permite ver ese notebook (puede ser privado).")
    if r.status_code == 404:
        raise ErrorKaggle("Ese notebook no existe o ya no es público.")
    if r.status_code == 429:
        raise ErrorKaggle("Kaggle limitó las peticiones por un momento. Espera unos segundos y reintenta.")
    if r.status_code != 200:
        raise ErrorKaggle(f"Kaggle respondió {r.status_code}.")
    try:
        return r.json()
    except ValueError:
        raise ErrorKaggle("Kaggle devolvió una respuesta que no se puede leer.")


_cache: Dict[str, Tuple[float, Any]] = {}


def buscar(consulta: str = "", orden: str = "relevancia", pagina: int = 1, competicion: str = "",
           dataset: str = "", usuario: str = "", por_pagina: int = 20, tipo: str = "", votos_min: int = 0,
           dias: int = 0, gpu: Optional[bool] = None, padre: str = "") -> Dict[str, Any]:
    """ Notebooks de la comunidad.

    Kaggle filtra por texto, competición, dataset, autor («user») y notebook de origen
    («parentKernel»: las copias de uno). Lo demás lo ignora o lo rompe (medido:
    «kernelType» no cambia nada, «outputType» devuelve vacío, «language=python» también),
    así que el tipo, los votos mínimos, la antigüedad y la GPU se filtran aquí. Con esos
    filtros se piden 50 por página para que no queden páginas casi vacías.
    """
    locales = bool(tipo in ("notebook", "script") or votos_min or dias or gpu is not None)
    params = {"page": max(1, int(pagina)), "pageSize": 50 if locales else max(1, min(int(por_pagina), 50)),
              "sortBy": ORDENES.get(orden, "hotness")}
    if consulta.strip():
        params["search"] = consulta.strip()[:100]
    elif params["sortBy"] == "relevance":
        params["sortBy"] = "hotness"
    if competicion.strip():
        params["competition"] = competicion.strip()
    if dataset.strip():
        params["dataset"] = dataset.strip()
    if usuario.strip():
        params["user"] = usuario.strip()
    if padre.strip():
        params["parentKernel"] = ref_desde(padre)
    clave = json.dumps(params, sort_keys=True)
    guardado = _cache.get(clave)
    if guardado and time.time() - guardado[0] < 600:
        lista = guardado[1]
    else:
        datos = _pedir("kernels/list", params)
        lista = datos if isinstance(datos, list) else datos.get("kernels") or []
        _cache[clave] = (time.time(), lista)
    notebooks = [_normalizar(k) for k in lista if k.get("ref") and (k.get("language") or "python").lower() == "python"]
    antes = len(notebooks)
    if tipo in ("notebook", "script"):
        notebooks = [n for n in notebooks if (n["tipo"] or "notebook") == tipo]
    if votos_min:
        notebooks = [n for n in notebooks if (n["votos"] or 0) >= int(votos_min)]
    if dias:
        limite = datetime.now().timestamp() - int(dias) * 86400
        notebooks = [n for n in notebooks if _fecha(n["ejecutado"]) >= limite]
    if gpu is not None:
        notebooks = [n for n in notebooks if bool(n["gpu"]) == gpu]
    return {"notebooks": notebooks, "pagina": params["page"], "hay_mas": len(lista) >= params["pageSize"],
            "ocultos": antes - len(notebooks)}


def _fecha(texto: Optional[str]) -> float:
    try:
        return datetime.fromisoformat(str(texto).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _normalizar(k: Dict[str, Any]) -> Dict[str, Any]:
    return {"ref": k.get("ref"), "titulo": k.get("title"), "autor": k.get("author"),
            "votos": k.get("totalVotes"), "ejecutado": k.get("lastRunTime"),
            "lenguaje": k.get("language"), "tipo": k.get("kernelType"), "gpu": bool(k.get("enableGpu")),
            "datos": (k.get("competitionDataSources") or []) + (k.get("datasetDataSources") or []),
            "url": f"https://www.kaggle.com/code/{k.get('ref')}"}


def ref_desde(texto: str) -> str:
    """ «usuario/slug» a partir de un enlace de Kaggle o de la referencia tal cual """
    t = (texto or "").strip()
    m = re.search(r"kaggle\.com/(?:code/|kernels/)?([A-Za-z0-9_\-]+)/([A-Za-z0-9_\-.]+)", t)
    ref = f"{m.group(1)}/{m.group(2)}" if m else t.strip("/")
    ref = re.sub(r"/(?:notebook|edit|log|comments|input|output|data)$", "", ref)
    if not REF_VALIDA.match(ref) or ".." in ref:
        raise ErrorKaggle("Eso no es un notebook de Kaggle: pega un enlace como kaggle.com/code/usuario/nombre.")
    return ref


def _texto_de(fuente) -> str:
    return "".join(fuente) if isinstance(fuente, list) else str(fuente or "")


def _salidas_texto(celda: Dict[str, Any]) -> str:
    partes = []
    for s in celda.get("outputs") or []:
        if s.get("output_type") == "stream":
            partes.append(_texto_de(s.get("text")))
        elif "data" in s and "text/plain" in (s.get("data") or {}):
            partes.append(_texto_de(s["data"]["text/plain"]))
        elif s.get("output_type") == "error":
            partes.append(f"{s.get('ename')}: {s.get('evalue')}")
    texto = "\n".join(p for p in partes if p.strip())
    return texto[:3000]


def _ruta_notebook(ref: str) -> str:
    return os.path.join(carpeta(), "notebooks", ref.replace("/", "__") + ".json")


def abrir(texto: str, refrescar: bool = False) -> Dict[str, Any]:
    """ El notebook con sus celdas. Se guarda una semana en disco. """
    ref = ref_desde(texto)
    ruta = _ruta_notebook(ref)
    if not refrescar and os.path.exists(ruta) and time.time() - os.path.getmtime(ruta) < 7 * 86400:
        guardado = _leer_json(ruta)
        if guardado:
            return guardado
    usuario, slug = ref.split("/")
    datos = _pedir("kernels/pull", {"userName": usuario, "kernelSlug": slug}, obligar_cuenta=False)
    meta = datos.get("metadata") or {}
    blob = datos.get("blob") or {}
    fuente = blob.get("source") or ""
    if meta.get("kernelType") == "script" or blob.get("kernelType") == "script":
        celdas = [{"tipo": "code", "fuente": fuente, "salida": ""}]
        ipynb = None
    else:
        try:
            ipynb = json.loads(fuente)
        except ValueError:
            raise ErrorKaggle("El notebook descargado no se pudo leer.")
        celdas = [{"tipo": c.get("cell_type", "code"), "fuente": _texto_de(c.get("source")), "salida": _salidas_texto(c)}
                  for c in ipynb.get("cells") or [] if c.get("cell_type") in ("code", "markdown")]
    for i, c in enumerate(celdas):
        c["indice"] = i
    nb = {
        "ref": meta.get("ref") or ref, "titulo": meta.get("title") or slug, "autor": meta.get("author"),
        "votos": meta.get("totalVotes"), "version": meta.get("currentVersionNumber"),
        "lenguaje": meta.get("language"), "tipo": meta.get("kernelType"), "ejecutado": meta.get("lastRunTime"),
        "gpu": meta.get("enableGpu"), "competiciones": meta.get("competitionDataSources") or [],
        "datasets": meta.get("datasetDataSources") or [], "notebooks_fuente": meta.get("kernelDataSources") or [],
        "url": f"https://www.kaggle.com/code/{meta.get('ref') or ref}",
        "celdas": celdas, "ipynb": ipynb, "descargado": datetime.now().isoformat(timespec="seconds"),
        "licencia": "Los notebooks públicos de Kaggle se publican por defecto con licencia Apache 2.0 salvo que el autor indique otra.",
    }
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta + ".tmp", "w", encoding="utf-8") as f:
        json.dump(nb, f, ensure_ascii=False)
    os.replace(ruta + ".tmp", ruta)
    return nb


def vista(nb: Dict[str, Any]) -> Dict[str, Any]:
    """ Lo que viaja al navegador (sin el .ipynb completo, que puede ser grande) """
    v = {k: v for k, v in nb.items() if k != "ipynb"}
    v["lectura"] = lectura(nb["ref"])
    return v


def guardar_en_workspace(texto: str, workspace: str) -> Dict[str, Any]:
    """ El notebook en kaggle_notebooks/ del proyecto, listo para ejecutarlo en Prig.

    Las rutas de Kaggle (/kaggle/input/<slug>/…, ../input/…) se cambian por las de
    kaggle_datos/<slug>/ del proyecto, que es donde Prig baja los datos. El resto del
    notebook queda idéntico al original.
    """
    import kaggle_explorar
    nb = abrir(texto)
    destino_dir = os.path.join(workspace, "kaggle_notebooks")
    os.makedirs(destino_dir, exist_ok=True)
    nombre = nb["ref"].split("/")[1] + (".ipynb" if nb["ipynb"] is not None else ".py")
    destino = os.path.join(destino_dir, nombre)
    cambiadas = 0
    if nb["ipynb"] is not None:
        ipynb = json.loads(json.dumps(nb["ipynb"]))
        for c in ipynb.get("cells") or []:
            if c.get("cell_type") != "code":
                continue
            antes = _texto_de(c.get("source"))
            despues = kaggle_explorar.reescribir_rutas(antes, workspace)
            if despues != antes:
                cambiadas += 1
                c["source"] = despues.splitlines(keepends=True)
        contenido = json.dumps(ipynb, ensure_ascii=False, indent=1)
    else:
        antes = nb["celdas"][0]["fuente"]
        contenido = kaggle_explorar.reescribir_rutas(antes, workspace)
        cambiadas = int(contenido != antes)
    with open(destino, "w", encoding="utf-8") as f:
        f.write(contenido)
    datos = kaggle_explorar.datos_del_notebook(nb, workspace)
    faltan = [d["ref"] for d in datos if not d["descargado"]]
    return {"ruta": destino, "relativa": os.path.relpath(destino, workspace), "titulo": nb["titulo"],
            "datos": datos, "celdas_con_rutas": cambiadas,
            "aviso": ("Para ejecutarlo faltan sus datos: " + ", ".join(faltan) + ". Bájalos con «Descargar al proyecto».")
            if faltan else None}


# ===========================================================================
# Lectura con el modelo
# ===========================================================================

def esquema(nb: Dict[str, Any], hasta: Optional[int] = None) -> str:
    """ El notebook resumido en una línea por celda: títulos de markdown e inicio del código """
    lineas = []
    for c in nb["celdas"][: hasta if hasta is not None else len(nb["celdas"])]:
        primera = next((l.strip() for l in c["fuente"].splitlines() if l.strip()), "")
        if c["tipo"] == "markdown":
            if primera.startswith("#"):
                lineas.append(f"[{c['indice']}] {primera[:100]}")
        else:
            defs = re.findall(r"^\s*(?:def|class)\s+(\w+)|^\s*(\w+)\s*=", c["fuente"], re.M)
            nombres = [a or b for a, b in defs][:5]
            lineas.append(f"[{c['indice']}] código: {primera[:80]}" + (f"  (define: {', '.join(nombres)})" if nombres else ""))
    return "\n".join(lineas)[:6000]


NIVELES = {
    "principiante": "El alumno está empezando: explica cada término técnico la primera vez que aparece y ve línea por línea.",
    "intermedio": "El alumno conoce Python y pandas básico: explica las decisiones y lo que no es obvio, no la sintaxis.",
    "avanzado": "El alumno es avanzado: céntrate en por qué se hace así, alternativas, riesgos (fugas de datos, validación) y buenas prácticas.",
}

SISTEMA_CELDA = """Eres un científico de datos senior que lee un notebook de Kaggle JUNTO al alumno, celda
a celda, como un profesor al lado. Explica en español lo que hace ESTA celda en el contexto del notebook.

Estructura (encabezados «### »):
### Qué hace
Una o dos frases.
### Paso a paso
Las partes importantes del código explicadas en orden; cita el fragmento entre `comillas de código`.
### Datos y Columnas (solo si la celda lee, transforma, filtra o grafica datos)
Si la celda interactúa con columnas o archivos de datos, explica qué columnas concretas del dataset real se están usando, qué significan, cómo se están tratando los tipos o nulos y qué impacto tiene en los datos.
### Por qué aquí
Qué papel cumple en el flujo del notebook (usa el esquema y las celdas anteriores).
### Conceptos
Los conceptos de Python, pandas, estadística o ML que aparecen, en una línea cada uno.
### Diagrama del Algoritmo (solo si la celda entrena, define o transforma modelos de ML/DL o pipelines)
Si la celda involucra modelos o pipelines (ej. XGBoost, LightGBM, CatBoost, Random Forest, SVM, k-Means, PCA, CNN, ResNet, Transformer, etc.), incluye un diagrama de flujo modular en bloque de código ```mermaid ... ``` conectando sus 4 bloques: [Entrada] -> [Transformación/División/Atención] -> [Pérdida/Optimización] -> [Inferencia/Métrica].
### Para pensar
Una pregunta o mini-reto para comprobar que se entendió.

No inventes resultados: si la celda muestra datos, di QUÉ mostraría, no valores concretos."""

SISTEMA_MARKDOWN = """Eres un científico de datos senior que lee un notebook de Kaggle junto al alumno. Esta
celda es TEXTO del autor. En español y en pocas líneas: resume la idea, explica los términos
técnicos que use y di qué conviene tener presente para las celdas de código que siguen."""

SISTEMA_GUIA = """Eres un científico de datos senior. Antes de leer un notebook de Kaggle con el alumno, le
das una guía de lectura en español, basada en el esquema, las celdas y la estructura de los datos disponibles.

Secciones (encabezados «## »):
## De qué trata
Objetivo del notebook y qué datos usa (menciona los datasets, tablas y columnas principales).
## El recorrido
Las etapas (por ejemplo: carga, exploración, limpieza, variables, modelo, evaluación) con los
números de celda donde empieza cada una: `celdas 3–7`. Si el notebook entrena modelos, incluye un diagrama de flujo general del pipeline en un bloque ```mermaid ... ```.
## Qué vas a aprender
Técnicas y conceptos concretos que aparecen.
## Antes de empezar
Lo que conviene saber para seguirlo, y cómo leerlo (qué celdas son clave y cuáles se pueden hojear)."""

SISTEMA_ESTUDIO_OPTIMO = """Eres un mentor y científico de datos senior especializado en aprendizaje activo de Machine Learning y Ciencia de Datos a través de proyectos reales de Kaggle.

Diseña una RUTA ÓPTIMA DE ESTUDIO personalizada para este notebook y sus datasets reales, diseñada para que el estudiante comprenda el flujo de trabajo completo, domine la teoría subyacente y sepa reutilizar el código en sus propios proyectos.

Estructura obligatoria con encabezados («## » y «### »):
## 1. Mapeo del Problema y los Datos
- Tipo de problema (clasificación, regresión, series temporales, NLP, visión, etc.) y métrica de evaluación (ROC-AUC, RMSE, F1, LogLoss, etc.).
- Relación de los datasets reales con el objetivo: qué representa cada fila, cuál es la variable objetivo (target) y qué variables predictoras son clave.

## 2. Flujo de Trabajo y Celdas Clave
Organiza el estudio en fases lógicas indicando los rangos de celdas a revisar:
- Fase A: Carga, Inspección y Calidad de Datos (celdas X-Y).
- Fase B: Análisis Exploratorio (EDA) e Hipótesis (celdas X-Y).
- Fase C: Ingeniería de Características y Preprocesamiento (celdas X-Y).
- Fase D: Modelado, Validación Cruzada y Tuning (celdas X-Y).
- Fase E: Inferencia, Post-procesamiento y Conclusiones (celdas X-Y).
(Si el notebook entrena modelos, incluye un diagrama de flujo modular en bloque ```mermaid ... ``` resumiendo la arquitectura de datos y modelado).

## 3. Patrones de Código Reutilizables
Identifica 2 a 4 técnicas o patrones de código excelentes que se usan en este notebook y que el estudiante debería guardar en su caja de herramientas (ej. imputación específica, encoding, optimización de memoria, cross-validation estratificado, pipeline de scikit-learn/PyTorch, etc.), con breve explicación de por qué son buenas prácticas.

## 4. Preguntas Socráticas y Retos de Aprendizaje
3 retos prácticos ordenados por dificultad:
- Nivel Básico: Modificar un hiperparámetro o preprocesamiento en una celda específica.
- Nivel Intermedio: Crear una nueva feature o manejar valores nulos de forma alternativa.
- Nivel Avanzado: Diseñar una estrategia de validación diferente o mitigar un riesgo de fuga de datos (data leakage).

## 5. Próximos Pasos para Practicar en Prig IDE
Cómo transferir este código a tu editor local con el botón «Al editor», cómo ejecutarlo con datos en `kaggle_datos/` y qué experimento ejecutar primero."""


def _contexto(nb: Dict[str, Any], indice: int, contexto_datos: Optional[str] = None) -> str:
    c = nb["celdas"][indice]
    previas = []
    for p in nb["celdas"][max(0, indice - 3):indice]:
        previas.append(f"--- celda {p['indice']} ({p['tipo']}) ---\n{p['fuente'][:1500]}")
    base = (f"NOTEBOOK: «{nb['titulo']}» de {nb.get('autor')} · datos: {', '.join(nb['competiciones'] + nb['datasets']) or 'sin indicar'}\n\n"
            f"ESQUEMA:\n{esquema(nb)}\n\nCELDAS ANTERIORES:\n" + ("\n".join(previas) or "(ninguna)")
            + f"\n\nCELDA {indice} A EXPLICAR ({c['tipo']}):\n{c['fuente'][:5000]}"
            + (f"\n\nSALIDA GUARDADA:\n{c['salida']}" if c.get("salida") else ""))
    if contexto_datos and contexto_datos.strip():
        base += f"\n\nESTRUCTURA DE LOS DATASETS DISPONIBLES:\n{contexto_datos.strip()}"
    return base


def _ruta_explicaciones(ref: str) -> str:
    return os.path.join(carpeta(), "explicaciones", ref.replace("/", "__") + ".json")


_cerrojo = threading.Lock()


def explicaciones(ref: str) -> Dict[str, Any]:
    return _leer_json(_ruta_explicaciones(ref)) or {}


def _clave_explicacion(nb: Dict[str, Any], indice: int, nivel: str, modelo: str) -> str:
    huella = hashlib.sha1(nb["celdas"][indice]["fuente"].encode()).hexdigest()[:10]
    return f"{indice}:{nivel}:{modelo}:{huella}"


def guardar_explicacion(nb: Dict[str, Any], indice: Optional[int], nivel: str, modelo: str, texto: str):
    ref = nb["ref"]
    with _cerrojo:
        datos = explicaciones(ref)
        if indice is None:
            clave = "estudio:" + modelo if nivel == "estudio" else "guia:" + modelo
        else:
            clave = _clave_explicacion(nb, indice, nivel, modelo)
        datos[clave] = {"texto": texto, "fecha": datetime.now().isoformat(timespec="seconds"), "indice": indice}
        os.makedirs(os.path.dirname(_ruta_explicaciones(ref)), exist_ok=True)
        with open(_ruta_explicaciones(ref) + ".tmp", "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False)
        os.replace(_ruta_explicaciones(ref) + ".tmp", _ruta_explicaciones(ref))
    if indice is not None:
        marcar_leida(nb, indice)


def explicacion_guardada(nb: Dict[str, Any], indice: Optional[int], nivel: str, modelo: str) -> Optional[str]:
    if indice is None:
        clave = "estudio:" + modelo if nivel == "estudio" else "guia:" + modelo
    else:
        clave = _clave_explicacion(nb, indice, nivel, modelo)
    return (explicaciones(nb["ref"]).get(clave) or {}).get("texto")


def explicar(ai, modelo: str, nb: Dict[str, Any], indice: int, nivel: str = "intermedio",
             contexto_datos: Optional[str] = None):
    from desafios.tutor import flujo
    if not 0 <= indice < len(nb["celdas"]):
        raise ErrorKaggle("Esa celda no existe.")
    c = nb["celdas"][indice]
    if not c["fuente"].strip():
        return "Celda vacía."
    sistema = (SISTEMA_MARKDOWN if c["tipo"] == "markdown" else SISTEMA_CELDA) + "\n\n" + NIVELES.get(nivel, NIVELES["intermedio"])
    return (yield from flujo(ai, modelo, _contexto(nb, indice, contexto_datos), sistema, temperatura=0.3))


def guia(ai, modelo: str, nb: Dict[str, Any], contexto_datos: Optional[str] = None):
    from desafios.tutor import flujo
    primeras = "\n".join(f"--- celda {c['indice']} ({c['tipo']}) ---\n{c['fuente'][:800]}" for c in nb["celdas"][:6])
    prompt = (f"NOTEBOOK: «{nb['titulo']}» de {nb.get('autor')} · {len(nb['celdas'])} celdas · datos: "
              f"{', '.join(nb['competiciones'] + nb['datasets']) or 'sin indicar'}\n\nESQUEMA:\n{esquema(nb)}\n\nPRIMERAS CELDAS:\n{primeras}")
    if contexto_datos and contexto_datos.strip():
        prompt += f"\n\nDATASETS Y ESQUEMAS DISPONIBLES:\n{contexto_datos.strip()}"
    return (yield from flujo(ai, modelo, prompt, SISTEMA_GUIA, temperatura=0.3, pensar=True))


def estudio_optimo(ai, modelo: str, nb: Dict[str, Any], contexto_datos: Optional[str] = None):
    from desafios.tutor import flujo
    primeras = "\n".join(f"--- celda {c['indice']} ({c['tipo']}) ---\n{c['fuente'][:600]}" for c in nb["celdas"][:8])
    prompt = (f"NOTEBOOK: «{nb['titulo']}» de {nb.get('autor')} · {len(nb['celdas'])} celdas · datos: "
              f"{', '.join(nb['competiciones'] + nb['datasets']) or 'sin indicar'}\n\n"
              f"ESQUEMA COMPLETO:\n{esquema(nb)}\n\nMUESTRA DE CELDAS:\n{primeras}")
    if contexto_datos and contexto_datos.strip():
        prompt += f"\n\nESTRUCTURA Y ESTADÍSTICAS DE LOS DATASETS REALES:\n{contexto_datos.strip()}"
    return (yield from flujo(ai, modelo, prompt, SISTEMA_ESTUDIO_OPTIMO, temperatura=0.3, pensar=True))


def preguntar(ai, modelo: str, nb: Dict[str, Any], indice: Optional[int], mensajes: List[Dict[str, str]],
              contexto_datos: Optional[str] = None):
    from desafios.tutor import flujo
    sistema = ("Eres un científico de datos senior que lee con el alumno un notebook de Kaggle. Responde en español, claro "
               "y breve (menos de 200 palabras), apoyándote en el código del notebook y en la estructura de los datos reales. "
               "Si la pregunta es sobre algo que no está en el notebook ni en sus datos, dilo. Puedes mostrar fragmentos cortos de código.")
    contexto = _contexto(nb, indice, contexto_datos) if indice is not None and 0 <= indice < len(nb["celdas"]) else \
        f"NOTEBOOK: «{nb['titulo']}»\n\nESQUEMA:\n{esquema(nb)}" + (f"\n\nDATASETS:\n{contexto_datos.strip()}" if contexto_datos and contexto_datos.strip() else "")
    historial = "\n".join(f"{'Alumno' if m.get('rol') == 'usuario' else 'Profesor'}: {str(m.get('texto'))[:1500]}"
                          for m in (mensajes or [])[-10:])
    return (yield from flujo(ai, modelo, f"{contexto}\n\nCONVERSACIÓN:\n{historial}\nProfesor:", sistema, temperatura=0.4))


# ===========================================================================
# Lo leído (para el Perfil)
# ===========================================================================

def _ruta_lecturas() -> str:
    return os.path.join(carpeta(), "lecturas.json")


def lecturas() -> Dict[str, Any]:
    return _leer_json(_ruta_lecturas()) or {}


def lectura(ref: str) -> Dict[str, Any]:
    return lecturas().get(ref) or {"leidas": [], "total": 0}


def marcar_leida(nb: Dict[str, Any], indice: int):
    with _cerrojo:
        datos = lecturas()
        l = datos.setdefault(nb["ref"], {"titulo": nb["titulo"], "leidas": [], "total": len(nb["celdas"]), "empezado": datetime.now().isoformat(timespec="seconds")})
        if indice not in l["leidas"]:
            l["leidas"] = sorted(set(l["leidas"]) | {indice})
        l["total"] = len(nb["celdas"])
        l["titulo"] = nb["titulo"]
        l["ultima"] = datetime.now().isoformat(timespec="seconds")
        l["ultima_celda"] = indice
        os.makedirs(carpeta(), exist_ok=True)
        with open(_ruta_lecturas() + ".tmp", "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False)
        os.replace(_ruta_lecturas() + ".tmp", _ruta_lecturas())


def resumen_lecturas() -> List[Dict[str, Any]]:
    salida = [{"ref": ref, "titulo": l.get("titulo"), "leidas": len(l.get("leidas") or []), "total": l.get("total") or 0,
               "ultima": l.get("ultima"), "ultima_celda": l.get("ultima_celda")} for ref, l in lecturas().items()]
    return sorted(salida, key=lambda x: x.get("ultima") or "", reverse=True)
