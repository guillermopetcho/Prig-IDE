"""
Referencias de Deep Learning (DP / DL): libros, papers fundacionales y modernos, formularios (cheat sheets),
cursos y documentación oficial de arquitecturas profundas, optimización, visión, NLP, LLMs, modelos generativos,
Deep RL, multimodalidad y sistemas eficientes de inferencia y entrenamiento.

El catálogo vive en frontend/data/referencias_dp.json (versionado en el repositorio) y tiene tres usos:

  · Biblioteca → «Referencias DP»: navegar, leer (PDF dentro de Prig o en el navegador) y guardar el
    PDF en la biblioteca local para indexarlo con «Mi biblioteca».
  · Chat del Tutor Prig: `bloque_para_prompt(pregunta)` devuelve las referencias relacionadas de Deep Learning
    para que el modelo pueda citarlas (título, autores, año y enlace) con rigor.
  · docs/referencias-dp.md: la lista completa en Markdown clasificada por categoría y tipo.
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

RUTA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "data", "referencias_dp.json")
RUTA_MD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "referencias-dp.md")

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

CATEGORIAS: List[Dict[str, Any]] = [
    {
        "id": "fundamentos_dl",
        "nombre": "Fundamentos de Deep Learning y Perceptrón",
        "icono": "fa-brain",
        "claves": [
            "deep learning", "aprendizaje profundo", "red neuronal", "neural network",
            "perceptron", "mlp", "multicapa", "multilayer", "backpropagation", "retropropagacion",
            "gradiente descendente", "aproximacion universal", "universal approximation",
            "funcion de activacion", "activation function", "relu", "sigmoid", "tanh", "gelu", "swish"
        ]
    },
    {
        "id": "optimizacion_dinamica",
        "nombre": "Optimización, Regularización y Normalización",
        "icono": "fa-sliders",
        "claves": [
            "optimizacion", "optimization", "adam", "adamw", "rmsprop", "momentum", "learning rate", "tasa de aprendizaje",
            "cosine annealing", "warmup", "dropout", "batch normalization", "batch norm", "layer norm",
            "group norm", "weight decay", "inicializacion", "he initialization", "xavier initialization",
            "gradiente desvaneciente", "vanishing gradient", "gradient clipping", "recorte de gradiente"
        ]
    },
    {
        "id": "vision_cnn",
        "nombre": "Redes Convolucionales y Visión Artificial",
        "icono": "fa-eye",
        "claves": [
            "cnn", "convolucional", "convolutional", "computer vision", "vision artificial", "vision por computadora",
            "alexnet", "vgg", "inception", "resnet", "residual", "densenet", "efficientnet", "convnext",
            "u-net", "unet", "segmentacion", "segmentation", "deteccion de objetos", "object detection",
            "yolo", "faster r-cnn", "mask r-cnn", "vision transformer", "vit", "swin transformer", "sam", "segment anything"
        ]
    },
    {
        "id": "secuencias_atencion",
        "nombre": "Modelos Recurrentes, Secuencias y Mecanismo de Atención",
        "icono": "fa-arrows-rotate",
        "claves": [
            "rnn", "recurrente", "recurrent", "lstm", "gru", "seq2seq", "sequence to sequence",
            "mecanismo de atencion", "attention mechanism", "atencion aditiva", "bahdanau", "luong",
            "alineamiento", "bidireccional", "bilstm", "traduccion automatica", "nmt"
        ]
    },
    {
        "id": "transformers_llm",
        "nombre": "Transformers y Modelos de Lenguaje (LLMs)",
        "icono": "fa-microchip",
        "claves": [
            "transformer", "transformers", "self-attention", "autoatencion", "multi-head attention",
            "atencion multi-cabeza", "llm", "large language model", "modelo de lenguaje",
            "bert", "gpt", "gpt-2", "gpt-3", "gpt-4", "t5", "roberta", "deberta", "llama", "llama 2", "llama 3",
            "mistral", "deepseek", "qwen", "scaling laws", "leyes de escala", "chinchilla", "tokenizacion", "bpe"
        ]
    },
    {
        "id": "post_entrenamiento",
        "nombre": "Post-Entrenamiento, Alineación, RAG y Razonamiento",
        "icono": "fa-compass-drafting",
        "claves": [
            "post-entrenamiento", "post training", "fine-tuning", "ajuste fino", "instruction tuning",
            "rlhf", "dpo", "direct preference optimization", "lora", "qlora", "peft", "adapter",
            "rag", "retrieval augmented generation", "vector database", "embeddings",
            "chain of thought", "cot", "razonamiento", "reasoning", "tree of thoughts", "react", "prompt engineering"
        ]
    },
    {
        "id": "modelos_generativos",
        "nombre": "Modelos Generativos Profundos (VAE, GAN, Difusión)",
        "icono": "fa-wand-magic-sparkles",
        "claves": [
            "generativo", "generative", "vae", "variational autoencoder", "autocodificador variacional",
            "gan", "generative adversarial", "dcgan", "wgan", "stylegan", "difusion", "diffusion",
            "ddpm", "stable diffusion", "latent diffusion", "score-based", "flow matching", "normalizing flows"
        ]
    },
    {
        "id": "deep_rl",
        "nombre": "Deep Reinforcement Learning (Aprendizaje por Refuerzo)",
        "icono": "fa-chess-knight",
        "claves": [
            "reinforcement learning", "aprendizaje por refuerzo", "drl", "deep rl", "q-learning",
            "dqn", "deep q network", "policy gradient", "actor-critic", "actor critic", "trpo", "ppo",
            "sac", "soft actor critic", "ddpg", "alphago", "alphazero", "muzero", "bellman"
        ]
    },
    {
        "id": "multimodal_audio",
        "nombre": "Deep Learning Multimodal, Audio, Habla y Video",
        "icono": "fa-photo-film",
        "claves": [
            "multimodal", "vision language", "vlm", "clip", "blip", "llava", "flamingo", "whisper",
            "speech recognition", "reconocimiento de voz", "sintesis de voz", "tts", "wavenet",
            "video generation", "generacion de video", "sora", "audiocraft"
        ]
    },
    {
        "id": "gnn_geometric",
        "nombre": "Grafos, Deep Learning Geométrico y Bioinformática",
        "icono": "fa-diagram-project",
        "claves": [
            "gnn", "graph neural network", "redes sobre grafos", "gcn", "gat", "graphsage", "message passing",
            "geometric deep learning", "deep learning geometrico", "invarianza", "equivarianza", "alphafold",
            "plegamiento de proteinas", "moleculas", "molecular"
        ]
    },
    {
        "id": "sistemas_eficiencia",
        "nombre": "Sistemas, Eficiencia, Cuantización e Inferencia",
        "icono": "fa-bolt",
        "claves": [
            "sistemas dl", "eficiencia", "cuantizacion", "quantization", "gptq", "awq", "smoothquant",
            "gguf", "llama.cpp", "flashattention", "pagedattention", "vllm", "kv cache", "cache kv",
            "paralelismo", "pipeline parallelism", "tensor parallelism", "deepspeed", "zero", "megatron", "triton"
        ]
    },
    {
        "id": "frameworks_docs",
        "nombre": "Frameworks y Documentación Oficial de Deep Learning",
        "icono": "fa-book-open-reader",
        "claves": [
            "pytorch", "torch", "jax", "flax", "keras", "tensorflow", "huggingface", "transformers lib",
            "diffusers", "accelerate", "onnx", "tensorrt", "documentacion pytorch", "tutoriales dl"
        ]
    }
]

CATEGORIA_POR_ID = {c["id"]: c for c in CATEGORIAS}
TEMAS_GENERICOS = {"python", "introduccion", "datasets", "prediccion", "texto", "codigo", "programacion", "entrenamiento",
                   "atencion", "attention", "error", "errores", "deep", "learning"}

AGENTE = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 PrigIDE"


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


def _aparece(clave: str, texto: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(clave) + r"(?:s|es)?(?![a-z0-9])", texto) is not None


def relacionadas(texto: str, maximo: int = 5) -> List[Dict[str, Any]]:
    """ Referencias de Deep Learning que vienen al caso de una pregunta o texto.
    Prioriza formularios y libros para el estudio, y papers fundacionales para rigor. """
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
                                          "openai", "hugging face", "keras", "anthropic", "deepmind", "pytorch")))
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
    lineas = ["REFERENCIAS DE DEEP LEARNING (REFERENCIAS DP) de la biblioteca de Prig relacionadas con la pregunta (catálogo verificado). "
              "Si alguna viene al caso, cítala al final con su enlace en Markdown, así: [Título](url) — Autores, año. "
              "No inventes páginas ni enlaces que no estén en esta lista:"]
    for r in refs:
        enlace = r["url_pdf"] if r.get("url", "").startswith("https://doi.org/") and r.get("url_pdf") else r["url"]
        lineas.append(f"- [{TIPOS.get(r.get('tipo'), r.get('tipo'))}] [{r['titulo']}]({enlace}) — {cita_corta(r)}"
                      + (f": {r['descripcion']}" if r.get("descripcion") else ""))
    return "\n".join(lineas), refs


def resumen_publico(r: Dict[str, Any]) -> Dict[str, Any]:
    return {k: r.get(k) for k in ("id", "titulo", "autores", "anio", "tipo", "url", "url_pdf", "categorias", "acceso")} | {
        "cita": cita_corta(r)}


def _guardar(refs: List[Dict[str, Any]], ruta: str = RUTA):
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(refs, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, ruta)
    _cache["datos"] = None


def markdown(ruta: str = RUTA, destino: str = RUTA_MD) -> str:
    """ docs/referencias-dp.md: el catálogo por familia de Deep Learning y por tipo """
    datos = cargar(ruta)
    refs = [r for r in datos["referencias"] if r.get("estado") != "caido"]
    lineas = [
        "# Referencias de Deep Learning (Referencias DP)", "",
        "Catálogo exhaustivo de libros, papers fundacionales y de vanguardia, formularios (cheat sheets), cursos y documentación "
        "oficial de Deep Learning (aprendizaje profundo), clasificados por área y tipo. "
        "Solo enlaces oficiales, directos y gratuitos (arXiv, sitios oficiales de autores, editoriales abiertas); "
        "las obras con acceso cerrado se identifican con 💲. Se consultan desde Prig en **Biblioteca → 🧠 REFERENCIAS DP**, "
        "y el Tutor Prig las cita contextualmente cuando se consulta sobre arquitecturas y modelos profundos.", "",
        f"Generado desde `frontend/data/referencias_dp.json` ({len(refs)} referencias).", "",
        "## Índice", ""
    ]
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
    if "--markdown" in args:
        print("markdown generado en:", markdown())
