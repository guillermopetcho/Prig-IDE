"""
Referencias de Machine Learning: libros, papers, formularios (hojas de fórmulas / cheat sheets), cursos y
documentación de todos los modelos de ML, ordenados por familia de modelo.

El catálogo vive en frontend/data/referencias_ml.json (versionado en el repositorio) y tiene tres usos:

  · Biblioteca → «Referencias ML»: navegar, leer (PDF dentro de Prig o en el navegador) y guardar el
    PDF en la biblioteca local para indexarlo.
  · Chat de cualquier sección: `bloque_para_prompt(pregunta)` devuelve las referencias relacionadas para
    que el modelo pueda citarlas (título, autores, año y enlace) cuando vengan al caso.
  · docs/referencias-ml.md: la misma lista en Markdown, generada con `--markdown`.

Solo enlaces oficiales y gratuitos (arXiv, sitios de los autores, editoriales en acceso abierto,
proceedings abiertos); los papers de pago se listan con su DOI y `acceso: "pago"`.

Nada se escribe de memoria: `python backend/referencias_ml.py --completar` toma de la API de arXiv el
título, los autores, el año y el resumen de cada paper con id de arXiv, y `--verificar` abre cada enlace
y marca el que no responde (o el de arXiv cuyo título no coincide).
"""

import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Tuple

RUTA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "data", "referencias_ml.json")
RUTA_MD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "referencias-ml.md")

TIPOS = {
    "libro": "Libro",
    "paper": "Paper",
    "survey": "Survey / tutorial académico",
    "formulario": "Formulario / cheat sheet",
    "apuntes": "Apuntes de curso",
    "curso": "Curso en línea",
    "articulo": "Artículo divulgativo",
    "documentacion": "Documentación oficial",
}

# Familias de modelos, en el orden en que se muestran. `claves`: cómo se nombra el tema en una pregunta
# (español e inglés, sin tildes); con eso se eligen las referencias para el chat.
CATEGORIAS: List[Dict[str, Any]] = [
    {"id": "fundamentos", "nombre": "Fundamentos y teoría del aprendizaje", "icono": "fa-graduation-cap",
     "claves": ["machine learning", "aprendizaje automatico", "aprendizaje estadistico", "statistical learning",
                "sesgo varianza", "bias variance", "sobreajuste", "overfitting", "validacion cruzada", "cross validation",
                "teoria del aprendizaje", "learning theory", "pac", "vc dimension", "generalizacion", "regularizacion"]},
    {"id": "matematicas", "nombre": "Matemáticas para ML (álgebra, cálculo, probabilidad)", "icono": "fa-square-root-variable",
     "claves": ["algebra lineal", "linear algebra", "matriz", "matrices", "calculo", "derivada", "gradiente", "jacobiano",
                "probabilidad", "probability", "estadistica", "statistics", "teoria de la informacion", "entropia",
                "information theory", "divergencia kl", "kl divergence", "svd", "autovalores", "eigen",
                "teorema de bayes", "bayes theorem", "distribucion normal", "varianza", "esperanza"]},
    {"id": "optimizacion", "nombre": "Optimización", "icono": "fa-arrow-trend-down",
     "claves": ["optimizacion", "optimization", "descenso de gradiente", "gradient descent", "sgd", "adam", "adamw",
                "momentum", "learning rate", "tasa de aprendizaje", "convexa", "convex", "newton", "lbfgs"]},
    {"id": "lineales", "nombre": "Regresión lineal, regularización y GLM", "icono": "fa-chart-line",
     "claves": ["regresion lineal", "linear regression", "minimos cuadrados", "least squares", "ols", "ridge", "lasso",
                "elastic net", "glm", "modelo lineal generalizado", "regresion logistica", "logistic regression",
                "softmax", "poisson"]},
    {"id": "bayesianos", "nombre": "Modelos probabilísticos y bayesianos", "icono": "fa-dice",
     "claves": ["bayes", "bayesiano", "bayesian", "naive bayes", "inferencia variacional", "variational inference",
                "mcmc", "monte carlo", "hamiltonian", "em", "expectation maximization", "mezcla de gaussianas",
                "gaussian mixture", "gmm", "modelo grafico", "graphical model", "hmm", "markov oculto", "hidden markov",
                "proceso gaussiano", "gaussian process", "gp", "kalman"]},
    {"id": "kernels", "nombre": "SVM y métodos de kernel", "icono": "fa-vector-square",
     "claves": ["svm", "support vector", "maquina de vectores de soporte", "vectores de soporte", "kernel", "margen",
                "margin", "smo", "kernel pca", "one class svm", "knn", "vecinos mas cercanos", "nearest neighbor"]},
    {"id": "arboles", "nombre": "Árboles de decisión y ensembles", "icono": "fa-tree",
     "claves": ["arbol de decision", "arboles de decision", "decision tree", "cart", "id3", "c4.5", "random forest",
                "bosque aleatorio", "bosques aleatorios", "bagging", "boosting", "adaboost", "gradient boosting",
                "xgboost", "lightgbm", "catboost", "gbm", "extra trees", "ensemble", "ensamble"]},
    {"id": "no_supervisado", "nombre": "Clustering, reducción de dimensión y anomalías", "icono": "fa-circle-nodes",
     "claves": ["clustering", "agrupamiento", "k-means", "kmeans", "k means", "dbscan", "hdbscan", "clustering jerarquico",
                "hierarchical clustering", "espectral", "spectral clustering", "pca", "componentes principales",
                "principal component", "t-sne", "tsne", "umap", "reduccion de dimension", "dimensionality reduction", "ica",
                "nmf", "anomalias", "anomaly detection", "outlier", "isolation forest", "lof"]},
    {"id": "redes_neuronales", "nombre": "Redes neuronales y entrenamiento profundo", "icono": "fa-brain",
     "claves": ["red neuronal", "redes neuronales", "neural network", "perceptron", "mlp", "backpropagation",
                "retropropagacion", "deep learning", "aprendizaje profundo", "dropout", "batch norm", "batchnorm",
                "normalizacion", "layer norm", "inicializacion", "initialization", "funcion de activacion", "relu",
                "residual", "resnet"]},
    {"id": "cnn", "nombre": "Redes convolucionales y visión por computadora", "icono": "fa-eye",
     "claves": ["cnn", "convolucional", "convolutional", "convolucion", "vision por computadora", "computer vision",
                "clasificacion de imagenes", "image classification", "deteccion de objetos", "object detection", "yolo",
                "r-cnn", "segmentacion", "segmentation", "u-net", "unet", "alexnet", "vgg", "resnet", "efficientnet",
                "vision transformer", "vit", "imagenet"]},
    {"id": "secuencias", "nombre": "Redes recurrentes y modelos de secuencia", "icono": "fa-arrows-rotate",
     "claves": ["rnn", "recurrente", "recurrent", "lstm", "gru", "seq2seq", "secuencia a secuencia", "sequence to sequence",
                "mecanismo de atencion", "attention mechanism", "capa de atencion", "traduccion automatica", "machine translation"]},
    {"id": "nlp", "nombre": "Procesamiento de lenguaje y embeddings", "icono": "fa-language",
     "claves": ["nlp", "procesamiento de lenguaje", "natural language", "word2vec", "glove", "embedding", "embeddings",
                "tokenizacion", "tokenizer", "tokenization", "bpe", "fasttext", "elmo", "bert"]},
    {"id": "transformers", "nombre": "Transformers y modelos de lenguaje (LLM)", "icono": "fa-robot",
     "claves": ["transformer", "transformers", "llm", "modelo de lenguaje", "language model", "gpt", "bert", "t5", "llama",
                "self-attention", "autoatencion", "mecanismo de atencion", "attention mechanism", "multi-head attention",
                "atencion multi-cabeza", "scaling laws", "leyes de escala", "fine-tuning",
                "ajuste fino", "lora", "rlhf", "instruct", "prompt", "chain of thought", "rag", "retrieval",
                "mixture of experts", "moe", "flashattention", "rope", "kv cache", "cuantizacion", "quantization", "dpo"]},
    {"id": "generativos", "nombre": "Modelos generativos (VAE, GAN, flujos, difusión)", "icono": "fa-wand-magic-sparkles",
     "claves": ["generativo", "generative", "vae", "autoencoder", "autocodificador", "variational autoencoder", "gan",
                "adversarial", "adversaria", "stylegan", "flujos normalizantes", "normalizing flow", "difusion", "diffusion",
                "ddpm", "stable diffusion", "score matching", "clip", "texto a imagen", "text to image"]},
    {"id": "refuerzo", "nombre": "Aprendizaje por refuerzo", "icono": "fa-chess-knight",
     "claves": ["refuerzo", "reinforcement learning", "rl", "q-learning", "q learning", "dqn", "policy gradient",
                "gradiente de politica", "ppo", "trpo", "actor critic", "actor-critic", "sac", "ddpg", "a3c", "mdp",
                "proceso de decision de markov", "alphago", "muzero", "bellman"]},
    {"id": "grafos", "nombre": "Redes neuronales sobre grafos", "icono": "fa-diagram-project",
     "claves": ["grafo", "grafos", "graph", "gnn", "gcn", "graph neural", "graph convolutional", "gat", "graphsage",
                "message passing", "paso de mensajes", "geometric deep learning", "node2vec", "deepwalk"]},
    {"id": "series_temporales", "nombre": "Series temporales y pronóstico", "icono": "fa-clock-rotate-left",
     "claves": ["serie temporal", "series temporales", "time series", "pronostico", "forecasting", "arima", "prophet",
                "estacionalidad", "seasonality", "deepar", "n-beats", "informer", "temporal fusion"]},
    {"id": "recomendacion", "nombre": "Sistemas de recomendación", "icono": "fa-thumbs-up",
     "claves": ["recomendacion", "recommender", "recommendation", "filtrado colaborativo", "collaborative filtering",
                "factorizacion de matrices", "matrix factorization", "wide and deep"]},
    {"id": "interpretabilidad", "nombre": "Interpretabilidad, explicabilidad y causalidad", "icono": "fa-magnifying-glass-chart",
     "claves": ["interpretabilidad", "interpretability", "explicabilidad", "explainability", "xai", "shap", "lime",
                "grad-cam", "saliency", "causalidad", "causal", "causal inference", "inferencia causal", "fairness",
                "equidad", "sesgo algoritmico"]},
    {"id": "practica", "nombre": "Práctica: evaluación, datos y MLOps", "icono": "fa-screwdriver-wrench",
     "claves": ["metricas", "metrics", "evaluacion", "evaluation", "roc", "auc", "precision", "recall", "f1",
                "matriz de confusion", "confusion matrix", "feature engineering", "ingenieria de caracteristicas",
                "preprocesamiento", "preprocessing", "desbalance", "imbalanced", "smote", "mlops", "produccion",
                "deployment", "scikit-learn", "sklearn", "pytorch", "tensorflow", "keras", "hiperparametros",
                "hyperparameter"]},
]
CATEGORIA_POR_ID = {c["id"]: c for c in CATEGORIAS}
# Palabras que aparecen en cualquier pregunta de programación: solas no hacen relevante una referencia
TEMAS_GENERICOS = {"python", "introduccion", "datasets", "prediccion", "texto", "codigo", "programacion", "entrenamiento",
                   "atencion", "attention", "error", "errores"}


# ---------------------------------------------------------------------------------------------- lectura
def _normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(ch for ch in t if not unicodedata.combining(ch))


_cache: Dict[str, Any] = {"mtime": None, "datos": None}


def cargar(ruta: str = RUTA) -> Dict[str, Any]:
    """ {"categorias", "tipos", "referencias"}; se relee si el archivo cambió """
    try:
        mtime = os.path.getmtime(ruta)
    except OSError:
        return {"categorias": CATEGORIAS, "tipos": TIPOS, "referencias": []}
    if _cache["datos"] is None or _cache["mtime"] != mtime or _cache.get("ruta") != ruta:
        with open(ruta, encoding="utf-8") as f:
            refs = json.load(f)
        refs = refs.get("referencias", refs) if isinstance(refs, dict) else refs
        orden_cat = {c["id"]: i for i, c in enumerate(CATEGORIAS)}
        orden_tipo = {t: i for i, t in enumerate(["formulario", "libro", "apuntes", "curso", "survey", "paper", "articulo", "documentacion"])}
        refs.sort(key=lambda r: (orden_cat.get(r["categorias"][0], 99), orden_tipo.get(r.get("tipo"), 9),
                                 r.get("anio") or 0, r.get("titulo", "")))
        _cache.update(mtime=mtime, ruta=ruta, datos={"categorias": CATEGORIAS, "tipos": TIPOS, "referencias": refs})
    return _cache["datos"]


def referencia(ref_id: str) -> Optional[Dict[str, Any]]:
    return next((r for r in cargar()["referencias"] if r.get("id") == ref_id), None)


def listar(q: str = "", categoria: str = "", tipo: str = "") -> List[Dict[str, Any]]:
    refs = cargar()["referencias"]
    if categoria:
        refs = [r for r in refs if categoria in r.get("categorias", [])]
    if tipo:
        refs = [r for r in refs if r.get("tipo") == tipo]
    if q:
        palabras = _normalizar(q).split()
        refs = [r for r in refs if all(p in _texto_busqueda(r) for p in palabras)]
    return refs


def _texto_busqueda(r: Dict[str, Any]) -> str:
    return _normalizar(" ".join([r.get("titulo", ""), " ".join(r.get("autores", [])), r.get("descripcion", ""),
                                 " ".join(r.get("temas", [])), str(r.get("anio") or ""), r.get("fuente", "")]))


# ---------------------------------------------------------------------------------------------- para el chat
def _aparece(clave: str, texto: str) -> bool:
    # admite el plural («transformer» encuentra «transformers», «red neuronal» no encuentra «redes»)
    return re.search(r"(?<![a-z0-9])" + re.escape(clave) + r"(?:s|es)?(?![a-z0-9])", texto) is not None


def relacionadas(texto: str, maximo: int = 5) -> List[Dict[str, Any]]:
    """ Las referencias que vienen al caso de una pregunta o un texto: por los temas de la pregunta
    (claves de cada familia) y por coincidencias con el título o los temas de cada referencia.
    Prioriza formularios y libros (lo que sirve para estudiar) y luego los papers fundacionales. """
    t = _normalizar(texto)
    if len(t) < 3:
        return []
    puntos_cat: Dict[str, float] = {}
    for c in CATEGORIAS:
        n = sum(1 + 0.2 * len(k.split()) for k in c["claves"] if _aparece(k, t))
        if n:
            puntos_cat[c["id"]] = n
    candidatas: List[Tuple[float, Dict[str, Any]]] = []
    peso_tipo = {"formulario": 1.2, "libro": 1.5, "apuntes": 1.0, "survey": 1.1, "paper": 0.8, "articulo": 0.6,
                 "documentacion": 0.4}
    for r in cargar()["referencias"]:
        if r.get("estado") == "caido":
            continue
        p = sum(puntos_cat.get(c, 0) * (1.0 if i == 0 else 0.5) for i, c in enumerate(r.get("categorias", [])))
        temas = [_normalizar(x) for x in r.get("temas", []) if _normalizar(x) not in TEMAS_GENERICOS]
        propios = sum(2.5 for x in temas if len(x) > 2 and _aparece(x, t))
        titulo = _normalizar(r.get("titulo", ""))
        # el nombre del paper o del libro en la pregunta («attention is all you need», «xgboost»)
        if len(titulo) > 8 and titulo in t:
            propios += 6
        if not p and not propios:
            continue
        candidatas.append((p + propios + peso_tipo.get(r.get("tipo"), 0.5) * (1 if p else 0), r))
    candidatas.sort(key=lambda x: -x[0])
    elegidas: List[Dict[str, Any]] = []
    por_tipo: Dict[str, int] = {}
    for puntos, r in candidatas:
        if puntos < 2.0:
            break
        # variedad: no cinco papers del mismo tema
        if por_tipo.get(r.get("tipo"), 0) >= 2:
            continue
        por_tipo[r.get("tipo")] = por_tipo.get(r.get("tipo"), 0) + 1
        elegidas.append(r)
        if len(elegidas) >= maximo:
            break
    return elegidas


def cita_corta(r: Dict[str, Any]) -> str:
    autores = r.get("autores") or []
    organizacion = len(autores) == 1 and (r.get("tipo") == "documentacion" or any(
        p in autores[0].lower() for p in ("developers", "team", "contributors", "foundation", "google", "meta", "microsoft",
                                          "openai", "hugging face", "keras", "mlflow", "dlr-rm")))
    quien = (autores[0] if organizacion else autores[0].split()[-1]) if autores else (r.get("fuente") or "")
    if len(autores) == 2:
        quien = f"{autores[0].split()[-1]} y {autores[1].split()[-1]}"
    elif len(autores) > 2:
        quien += " et al."
    anio = f", {r['anio']}" if r.get("anio") else ""
    return f"{quien}{anio}".strip(", ")


def bloque_para_prompt(texto: str, maximo: int = 5) -> Tuple[str, List[Dict[str, Any]]]:
    """ (bloque de texto para el prompt, referencias elegidas). Vacío si no hay nada relacionado """
    refs = relacionadas(texto, maximo)
    if not refs:
        return "", []
    lineas = ["REFERENCIAS DE LA BIBLIOTECA DE PRIG relacionadas con la pregunta (catálogo verificado). Si alguna "
              "viene al caso, cítala al final con su enlace en Markdown, así: [Título](url) — Autores, año. "
              "No cites ninguna que no esté en esta lista ni inventes páginas o capítulos:"]
    for r in refs:
        # si el enlace principal es la editorial (DOI) y hay PDF abierto del autor, se cita el que se puede leer
        enlace = r["url_pdf"] if r["url"].startswith("https://doi.org/") and r.get("url_pdf") else r["url"]
        lineas.append(f"- [{TIPOS.get(r.get('tipo'), r.get('tipo'))}] [{r['titulo']}]({enlace}) — {cita_corta(r)}"
                      + (f": {r['descripcion']}" if r.get("descripcion") else ""))
    return "\n".join(lineas), refs


def resumen_publico(r: Dict[str, Any]) -> Dict[str, Any]:
    """ Lo que la interfaz necesita para mostrar una referencia como chip o enlace """
    return {k: r.get(k) for k in ("id", "titulo", "autores", "anio", "tipo", "url", "url_pdf", "categorias", "acceso")} | {
        "cita": cita_corta(r)}


# ---------------------------------------------------------------------------------------------- completar y verificar
AGENTE = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 PrigIDE"


def _arxiv_metadatos(ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """ Título, autores, año y resumen desde la API oficial de arXiv (de a 40 por consulta, con pausa) """
    import xml.etree.ElementTree as ET
    ns = {"a": "http://www.w3.org/2005/Atom"}
    salida: Dict[str, Dict[str, Any]] = {}
    for i in range(0, len(ids), 40):
        lote = ids[i:i + 40]
        url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode({"id_list": ",".join(lote), "max_results": len(lote)})
        req = urllib.request.Request(url, headers={"User-Agent": AGENTE})
        raiz = ET.fromstring(urllib.request.urlopen(req, timeout=60).read())
        for e in raiz.findall("a:entry", ns):
            abs_id = (e.findtext("a:id", "", ns) or "").rsplit("/abs/", 1)[-1]
            base = re.sub(r"v\d+$", "", abs_id)
            titulo = " ".join((e.findtext("a:title", "", ns) or "").split())
            if not titulo or titulo == "Error":
                continue
            salida[base] = {
                "titulo": titulo,
                "autores": [" ".join((a.findtext("a:name", "", ns) or "").split()) for a in e.findall("a:author", ns)],
                "anio": int((e.findtext("a:published", "", ns) or "0")[:4] or 0),
                "resumen_original": " ".join((e.findtext("a:summary", "", ns) or "").split()),
            }
        time.sleep(3)  # pedido de arXiv: una consulta cada 3 s
    return salida


def completar(ruta: str = RUTA) -> Dict[str, Any]:
    """ Completa desde arXiv los papers que tienen `arxiv` y aún no tienen título verificado """
    with open(ruta, encoding="utf-8") as f:
        refs = json.load(f)
    pendientes = [r["arxiv"] for r in refs if r.get("arxiv") and not r.get("resumen_original")]
    meta = _arxiv_metadatos(pendientes) if pendientes else {}
    faltan = []
    for r in refs:
        if r.get("arxiv") and not r.get("resumen_original"):
            m = meta.get(r["arxiv"])
            if not m:
                faltan.append(r["arxiv"])
                continue
            # el título esperado (el que escribimos al proponerlo) tiene que coincidir con el real
            esperado = r.pop("titulo_esperado", "")
            if esperado and not _titulos_parecidos(esperado, m["titulo"]):
                r["estado"] = "revisar"
                r["nota_revision"] = f"arXiv {r['arxiv']} es «{m['titulo']}», no «{esperado}»"
            r.update({k: v for k, v in m.items() if not r.get(k) or k in ("titulo", "autores", "anio", "resumen_original")})
            r.setdefault("url", f"https://arxiv.org/abs/{r['arxiv']}")
            r.setdefault("url_pdf", f"https://arxiv.org/pdf/{r['arxiv']}")
            r.setdefault("fuente", "arXiv")
    _guardar(refs, ruta)
    return {"completados": len(pendientes) - len(faltan), "sin_respuesta": faltan}


def _titulos_parecidos(a: str, b: str) -> bool:
    pa = set(re.findall(r"[a-z0-9]{3,}", _normalizar(a)))
    pb = set(re.findall(r"[a-z0-9]{3,}", _normalizar(b)))
    if not pa or not pb:
        return False
    # Crossref a veces guarda solo el título sin el subtítulo («LOF» por «LOF: identifying…»): basta que
    # el más corto esté contenido en el otro
    return len(pa & pb) / min(len(pa), len(pb)) >= 0.6


def _titulo_crossref(doi: str) -> str:
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi)
    for intento in range(4):  # Crossref limita las consultas simultáneas: reintentar con espera
        codigo, _, cuerpo = _abrir(url)
        if codigo == 200:
            break
        if codigo == 404:
            return ""
        time.sleep(2 + 3 * intento)
    else:
        return ""
    try:
        return " ".join(((json.loads(cuerpo).get("message") or {}).get("title") or [""])[0].split())
    except ValueError:
        return ""


def _abrir(url: str, timeout: float = 25) -> Tuple[int, str, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": AGENTE, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read(400_000)
    except urllib.error.HTTPError as e:
        return e.code, "", b""
    except Exception as e:  # noqa: BLE001 — red, TLS, tiempo
        return 0, str(e)[:80], b""


def verificar(ruta: str = RUTA, solo_nuevas: bool = False) -> Dict[str, Any]:
    """ Abre cada enlace (url y url_pdf). Un PDF tiene que empezar con %PDF; una página, contener alguna
    palabra del título. Marca `estado`: "ok", "caido" o "revisar" (responde, pero no parece la obra). """
    import concurrent.futures as cf
    with open(ruta, encoding="utf-8") as f:
        refs = json.load(f)

    def una(r: Dict[str, Any]) -> Tuple[Dict[str, Any], str, str]:
        if solo_nuevas and r.get("verificado"):
            return r, r.get("estado", "ok"), ""
        problemas = []
        if r.get("verificado_navegador"):
            # Páginas que bloquean a los scripts o redirigen sin fin a un cliente sin cookies, abiertas y
            # comprobadas en un navegador real (fecha en el campo); solo se vuelve a mirar que no dé 404
            codigo, _, _ = _abrir(r["url"])
            return r, ("caido" if codigo == 404 else "ok"), ("url 404" if codigo == 404 else "")
        if r["url"].startswith("https://doi.org/"):
            # Las editoriales (IEEE, Wiley, ACM…) responden 403/202 a cualquier script: el DOI se comprueba en
            # Crossref, el registro oficial de DOI, comparando el título registrado con el nuestro
            titulo = _titulo_crossref(r["url"][len("https://doi.org/"):])
            if not titulo:
                return r, "caido", "el DOI no está registrado en Crossref"
            if not _titulos_parecidos(r["titulo"], titulo):
                return r, "revisar", f"el DOI es «{titulo}»"
            if r.get("url_pdf"):
                c2, t2, b2 = _abrir(r["url_pdf"])
                if c2 != 200 or b2[:5] != b"%PDF-":
                    return r, "revisar", f"pdf {c2 or t2}"
            return r, "ok", ""
        codigo, tipo, cuerpo = _abrir(r["url"])
        if codigo != 200:
            problemas.append(f"url {codigo or tipo}")
        elif "pdf" in tipo or cuerpo[:5] == b"%PDF-":
            if cuerpo[:5] != b"%PDF-":
                problemas.append("url no es un PDF")
        else:
            texto = _normalizar(cuerpo.decode("utf-8", "ignore"))
            palabras = [p for p in re.findall(r"[a-z0-9]{4,}", _normalizar(r["titulo"]))][:6]
            if palabras and not any(p in texto for p in palabras):
                problemas.append("la página no menciona el título")
        if r.get("url_pdf") and r["url_pdf"] != r["url"]:
            c2, t2, b2 = _abrir(r["url_pdf"])
            if c2 != 200 or b2[:5] != b"%PDF-":
                problemas.append(f"pdf {c2 or t2}")
        if not problemas:
            return r, "ok", ""
        return r, ("caido" if any(p.startswith(("url ", "pdf 0", "url no")) for p in problemas) else "revisar"), "; ".join(problemas)

    resumen = {"ok": 0, "caido": [], "revisar": []}
    with cf.ThreadPoolExecutor(8) as ex:
        for r, estado, detalle in ex.map(una, refs):
            if estado == "ok" and r.get("estado") == "revisar" and r.get("nota_revision"):
                estado = "revisar"  # el título de arXiv no coincidía: eso no lo arregla que el enlace abra
            r["estado"] = estado
            r["verificado"] = time.strftime("%Y-%m-%d")
            if detalle:
                r["nota_verificacion"] = detalle
            else:
                r.pop("nota_verificacion", None)
            if estado == "ok":
                resumen["ok"] += 1
            else:
                resumen[estado].append(f"{r['id']}: {detalle or r.get('nota_revision', '')}")
    _guardar(refs, ruta)
    return resumen


def _guardar(refs: List[Dict[str, Any]], ruta: str = RUTA):
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(refs, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, ruta)
    _cache["datos"] = None


def markdown(ruta: str = RUTA, destino: str = RUTA_MD) -> str:
    """ docs/referencias-ml.md: el catálogo por familia de modelo y por tipo """
    datos = cargar(ruta)
    refs = [r for r in datos["referencias"] if r.get("estado") != "caido"]
    lineas = ["# Referencias de Machine Learning", "",
              "Libros, papers, formularios (cheat sheets), apuntes y documentación de los modelos de machine learning, "
              "ordenados por familia de modelo. Solo enlaces oficiales y gratuitos; los que son de pago llevan la "
              "marca 💲. Se consultan desde Prig en **Biblioteca → 🔗 REFERENCIAS ML**, y el chat de cualquier "
              "sección las cita cuando la pregunta trata de su tema.", "",
              f"Generado desde `frontend/data/referencias_ml.json` ({len(refs)} referencias). Para agregar una: "
              "añadirla al JSON (con `arxiv` si es de arXiv) y correr "
              "`python backend/referencias_ml.py --completar --verificar --markdown`.", "",
              "## Índice", ""]
    for c in CATEGORIAS:
        n = sum(1 for r in refs if r["categorias"][0] == c["id"])
        if n:
            ancla = re.sub(r"[^a-z0-9 -]", "", _normalizar(c["nombre"])).replace(" ", "-")
            lineas.append(f"- [{c['nombre']}](#{ancla}) ({n})")
    for c in CATEGORIAS:
        propias = [r for r in refs if r["categorias"][0] == c["id"]]
        if not propias:
            continue
        lineas += ["", f"## {c['nombre']}"]
        for tipo, nombre in TIPOS.items():
            del_tipo = [r for r in propias if r.get("tipo") == tipo]
            if not del_tipo:
                continue
            lineas += ["", f"### {nombre}", ""]
            for r in del_tipo:
                pago = " 💲" if r.get("acceso") == "pago" else ""
                pdf = f" · [PDF]({r['url_pdf']})" if r.get("url_pdf") and r["url_pdf"] != r["url"] else ""
                desc = f" — {r['descripcion']}" if r.get("descripcion") else ""
                autores = ", ".join(r.get("autores", [])[:4]) + (" et al." if len(r.get("autores", [])) > 4 else "")
                lineas.append(f"- **[{r['titulo']}]({r['url']})**{pago} · {autores}{' (' + str(r['anio']) + ')' if r.get('anio') else ''}{pdf}{desc}")
    texto = "\n".join(lineas) + "\n"
    with open(destino, "w", encoding="utf-8") as f:
        f.write(texto)
    return destino


if __name__ == "__main__":
    args = set(sys.argv[1:])
    if "--completar" in args:
        print("completar:", json.dumps(completar(), ensure_ascii=False))
    if "--verificar" in args:
        r = verificar(solo_nuevas="--nuevas" in args)
        print("verificar:", r["ok"], "ok ·", len(r["caido"]), "caídos ·", len(r["revisar"]), "a revisar")
        for linea in r["caido"] + r["revisar"]:
            print("  ", linea)
    if "--markdown" in args:
        print("markdown:", markdown())
