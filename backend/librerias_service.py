import os
import json
import uuid
import time
import shutil
from datetime import datetime
from typing import List, Dict, Any, Optional

LIBRERIAS_DEFAULT = [
    {
        "id": "numpy",
        "nombre": "NumPy",
        "repo": "numpy/numpy",
        "doc_url": "https://numpy.org/doc/stable/",
        "descripcion": "Cálculo tensorial y numérico de alto rendimiento, álgebra lineal, transformadas de Fourier y arrays multidimensionales (ndarray).",
        "modulos_clave": ["numpy.linalg", "numpy.random", "numpy.fft", "numpy.ma", "numpy.polynomial"],
        "color": "#4DABCF",
        "tags": ["tensores", "matrices", "algebra-lineal", "calculo-numerico"]
    },
    {
        "id": "matplotlib",
        "nombre": "Matplotlib",
        "repo": "matplotlib/matplotlib",
        "doc_url": "https://matplotlib.org/stable/contents.html",
        "descripcion": "Trazado y visualización completa 2D y 3D en Python. Soporta gráficos estáticos, interactivos y publicación científica con pyplot.",
        "modulos_clave": ["matplotlib.pyplot", "matplotlib.figure", "matplotlib.axes", "matplotlib.animation", "mpl_toolkits.mplot3d"],
        "color": "#11557C",
        "tags": ["visualizacion", "graficos", "pyplot", "ciencia-de-datos"]
    },
    {
        "id": "pandas",
        "nombre": "Pandas",
        "repo": "pandas-dev/pandas",
        "doc_url": "https://pandas.pydata.org/docs/",
        "descripcion": "Estructuras de datos DataFrame y Series para manipulación, limpieza, unión, pivote y análisis estadístico tabular veloz.",
        "modulos_clave": ["pandas.DataFrame", "pandas.Series", "pandas.read_csv", "pandas.merge", "pandas.pivot_table"],
        "color": "#130754",
        "tags": ["dataframes", "datos-tabulares", "limpieza", "series-temporales"]
    },
    {
        "id": "scikit-learn",
        "nombre": "Scikit-Learn",
        "repo": "scikit-learn/scikit-learn",
        "doc_url": "https://scikit-learn.org/stable/",
        "descripcion": "Herramientas eficientes para análisis predictivo y machine learning: regresión, clasificación, clustering, reducción de dimensionalidad y pipelines.",
        "modulos_clave": ["sklearn.pipeline", "sklearn.model_selection", "sklearn.preprocessing", "sklearn.ensemble", "sklearn.metrics"],
        "color": "#F7931E",
        "tags": ["machine-learning", "clasificacion", "regresion", "clustering", "pipeline"]
    },
    {
        "id": "pytorch",
        "nombre": "PyTorch",
        "repo": "pytorch/pytorch",
        "doc_url": "https://pytorch.org/docs/stable/index.html",
        "descripcion": "Framework líder de Deep Learning con tensores acelerados en GPU, autograd (diferenciación automática dinámica) y módulos neurales.",
        "modulos_clave": ["torch.nn", "torch.optim", "torch.utils.data", "torch.autograd", "torch.cuda"],
        "color": "#EE4C2C",
        "tags": ["deep-learning", "redes-neuronales", "autograd", "gpu", "tensores"]
    },
    {
        "id": "seaborn",
        "nombre": "Seaborn",
        "repo": "mwaskom/seaborn",
        "doc_url": "https://seaborn.pydata.org/",
        "descripcion": "Visualización de datos estadísticos atractiva y orientada a datasets, construida sobre matplotlib e integrada con DataFrames de pandas.",
        "modulos_clave": ["seaborn.heatmap", "seaborn.pairplot", "seaborn.histplot", "seaborn.boxplot", "seaborn.FacetGrid"],
        "color": "#388E3C",
        "tags": ["visualizacion", "estadistica", "distribuciones", "correlacion"]
    },
    {
        "id": "scipy",
        "nombre": "SciPy",
        "repo": "scipy/scipy",
        "doc_url": "https://docs.scipy.org/doc/scipy/",
        "descripcion": "Ecosistema de algoritmos científicos: optimización de funciones, integración numérica, ecuaciones diferenciales y procesamiento de señales.",
        "modulos_clave": ["scipy.optimize", "scipy.stats", "scipy.integrate", "scipy.signal", "scipy.spatial"],
        "color": "#0054A6",
        "tags": ["calculo-cientifico", "optimizacion", "estadistica", "senales"]
    },
    {
        "id": "tensorflow",
        "nombre": "TensorFlow / Keras",
        "repo": "tensorflow/tensorflow",
        "doc_url": "https://www.tensorflow.org/api_docs",
        "descripcion": "Plataforma integral de Machine Learning y Deep Learning con soporte de grafos, tensores, entrenamiento distribuido y despliegue.",
        "modulos_clave": ["tf.keras.layers", "tf.keras.models", "tf.data", "tf.GradientTape", "tf.saved_model"],
        "color": "#FF6F00",
        "tags": ["deep-learning", "keras", "produccion", "grafos"]
    },
    {
        "id": "transformers",
        "nombre": "Transformers (Hugging Face)",
        "repo": "huggingface/transformers",
        "doc_url": "https://huggingface.co/docs/transformers/index",
        "descripcion": "Modelos State-of-the-Art de procesamiento de lenguaje natural (LLMs), visión artificial y audio, con soporte PyTorch y JAX.",
        "modulos_clave": ["transformers.AutoModel", "transformers.AutoTokenizer", "transformers.pipeline", "transformers.Trainer"],
        "color": "#FFD21E",
        "tags": ["llm", "nlp", "atencion", "embeddings", "huggingface"]
    }
]

class LibreriasService:
    def __init__(self, base_dir: str = None):
        if not base_dir:
            base_dir = os.environ.get("PRIG_BOOKS_DIR", os.path.expanduser("~/.prig_books"))
        self.base_dir = os.path.abspath(base_dir)
        self.librerias_dir = os.path.join(self.base_dir, "librerias")
        self.citas_dir = self.librerias_dir
        os.makedirs(self.librerias_dir, exist_ok=True)
        self.custom_list_file = os.path.join(self.librerias_dir, "lista_librerias.json")
        self._init_samples()

    def _init_samples(self):
        """ Inicializa citas de muestra técnicas para librerías clave si no existen aún """
        np_path = os.path.join(self.librerias_dir, "numpy.json")
        if not os.path.exists(np_path):
            sample_np = {
                "libreria": "numpy",
                "nombre": "NumPy",
                "repo": "numpy/numpy",
                "total_citas": 2,
                "fecha_actualizacion": datetime.now().isoformat(),
                "citas": [
                    {
                        "id": "lib_np_1",
                        "tema": "Broadcasting y Reshape eficiente",
                        "modulo": "numpy",
                        "funcion": "np.broadcast_to / reshape",
                        "snippet": "import numpy as np\nx = np.array([1, 2, 3])\n# Expansión de dimensiones sin duplicar memoria\ny = np.broadcast_to(x, (3, 3))\nprint(y)",
                        "explicacion": "El broadcasting de NumPy permite realizar operaciones vectoriales entre arrays de diferentes dimensiones sin copiar datos en memoria física.",
                        "parametros_clave": ["shape", "subok"],
                        "tags": ["broadcasting", "memoria", "rendimiento"],
                        "fecha": datetime.now().isoformat()
                    },
                    {
                        "id": "lib_np_2",
                        "tema": "Operaciones Matriciales y Descomposición SVD",
                        "modulo": "numpy.linalg",
                        "funcion": "np.linalg.svd",
                        "snippet": "U, S, Vt = np.linalg.svd(matriz_datos)\n# U: vectores singulares izquierdos, S: valores singulares",
                        "explicacion": "Calcula la descomposición en valores singulares (SVD) de una matriz, base de PCA y reducción de dimensionalidad.",
                        "parametros_clave": ["a", "full_matrices", "compute_uv"],
                        "tags": ["svd", "algebra-lineal", "pca"],
                        "fecha": datetime.now().isoformat()
                    }
                ]
            }
            try:
                with open(np_path, 'w', encoding='utf-8') as f:
                    json.dump(sample_np, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

        plt_path = os.path.join(self.librerias_dir, "matplotlib.json")
        if not os.path.exists(plt_path):
            sample_plt = {
                "libreria": "matplotlib",
                "nombre": "Matplotlib",
                "repo": "matplotlib/matplotlib",
                "total_citas": 1,
                "fecha_actualizacion": datetime.now().isoformat(),
                "citas": [
                    {
                        "id": "lib_plt_1",
                        "tema": "Creación limpia de Subplots Orientados a Objetos",
                        "modulo": "matplotlib.pyplot",
                        "funcion": "plt.subplots",
                        "snippet": "import matplotlib.pyplot as plt\nfig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4), sharey=True)\nax1.plot(x, y1, color='#89b4fa', label='Train Loss')\nax1.set_title('Entrenamiento')\nax2.plot(x, y2, color='#a6e3a1', label='Val Loss')\nax2.set_title('Validación')\nplt.tight_layout()\nplt.show()",
                        "explicacion": "La API orientada a objetos de Matplotlib (usando fig y ax) es más robusta y legible que el estilo procedimental simple.",
                        "parametros_clave": ["nrows", "ncols", "figsize", "sharey"],
                        "tags": ["subplots", "orientado-a-objetos", "layout"],
                        "fecha": datetime.now().isoformat()
                    }
                ]
            }
            try:
                with open(plt_path, 'w', encoding='utf-8') as f:
                    json.dump(sample_plt, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

    def list_libraries(self) -> List[Dict[str, Any]]:
        customs = []
        if os.path.exists(self.custom_list_file):
            try:
                with open(self.custom_list_file, 'r', encoding='utf-8') as f:
                    customs = json.load(f)
            except Exception:
                customs = []

        all_libs = {lib["id"]: dict(lib) for lib in LIBRERIAS_DEFAULT}
        for c in customs:
            all_libs[c["id"]] = c

        # Calcular número de citas guardadas en disco para cada una
        result = []
        for lid, lib in all_libs.items():
            citas_file = os.path.join(self.librerias_dir, f"{lid}.json")
            num_citas = 0
            if os.path.exists(citas_file):
                try:
                    with open(citas_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        num_citas = len(data.get("citas", []))
                except Exception:
                    num_citas = 0
            lib_info = dict(lib)
            lib_info["total_citas"] = num_citas
            lib_info["archivo_json"] = f"{lid}.json"
            result.append(lib_info)

        return result

    def add_library(self, repo: str, name: Optional[str] = None, desc: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        nombre = kwargs.get("nombre") or name
        descripcion = kwargs.get("descripcion") or desc
        github_repo = kwargs.get("github_repo") or repo

        repo_clean = github_repo.strip().replace("https://github.com/", "").strip("/")
        if "/" not in repo_clean:
            return {"error": "Formato de repositorio inválido. Usa 'usuario/repo' (ej: huggingface/datasets)."}

        owner, repo_name = repo_clean.split("/", 1)
        lid = repo_name.lower().replace(".", "-")

        customs = []
        if os.path.exists(self.custom_list_file):
            try:
                with open(self.custom_list_file, 'r', encoding='utf-8') as f:
                    customs = json.load(f)
            except Exception:
                customs = []

        entry = {
            "id": lid,
            "nombre": nombre or repo_name.capitalize(),
            "repo": repo_clean,
            "doc_url": f"https://github.com/{repo_clean}",
            "descripcion": descripcion or f"Repositorio y librería de GitHub {repo_clean}",
            "modulos_clave": [repo_name],
            "color": "#cba6f7",
            "tags": ["github", "custom-repo", repo_name]
        }

        # Actualizar si existe o agregar
        customs = [c for c in customs if c.get("id") != lid]
        customs.append(entry)

        try:
            with open(self.custom_list_file, 'w', encoding='utf-8') as f:
                json.dump(customs, f, indent=2, ensure_ascii=False)
            return {"success": True, "ok": True, "library": entry}
        except Exception as e:
            return {"error": f"Error guardando librería: {e}"}

    def get_library_citations(self, lib_id: str) -> Dict[str, Any]:
        lid = lib_id.lower().strip()
        citas_path = os.path.join(self.librerias_dir, f"{lid}.json")

        if os.path.exists(citas_path):
            try:
                with open(citas_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error leyendo {citas_path}: {e}")

        # Estructura inicial
        all_libs = {l["id"]: l for l in self.list_libraries()}
        meta = all_libs.get(lid) or {"nombre": lid.capitalize(), "repo": lid}

        initial = {
            "libreria": lid,
            "nombre": meta.get("nombre", lid.capitalize()),
            "repo": meta.get("repo", ""),
            "archivo_json": f"{lid}.json",
            "total_citas": 0,
            "fecha_actualizacion": datetime.now().isoformat(),
            "citas": []
        }
        try:
            with open(citas_path, 'w', encoding='utf-8') as f:
                json.dump(initial, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
        return initial

    def save_library_citation(self, lib_id: str, citation_data: Dict[str, Any]) -> Dict[str, Any]:
        current = self.get_library_citations(lib_id)
        lid = current.get("libreria", lib_id.lower())
        citas_path = os.path.join(self.librerias_dir, f"{lid}.json")

        cid = citation_data.get("id") or f"lib_cita_{int(time.time())}_{uuid.uuid4().hex[:4]}"
        entry = {
            "id": cid,
            "tema": (citation_data.get("tema") or "Uso de API").strip(),
            "modulo": (citation_data.get("modulo") or lid).strip(),
            "funcion": (citation_data.get("funcion") or citation_data.get("funcion_o_clase") or "").strip(),
            "snippet": (citation_data.get("snippet") or citation_data.get("codigo_ejemplo") or "").strip(),
            "explicacion": (citation_data.get("explicacion") or "").strip(),
            "parametros_clave": citation_data.get("parametros_clave") if isinstance(citation_data.get("parametros_clave"), list) else [p.strip() for p in str(citation_data.get("parametros_clave") or "").split(",") if p.strip()],
            "tags": citation_data.get("tags") if isinstance(citation_data.get("tags"), list) else [t.strip() for t in str(citation_data.get("tags") or "").split(",") if t.strip()],
            "fecha": datetime.now().isoformat()
        }

        existing = current.get("citas", [])
        found_idx = next((i for i, c in enumerate(existing) if c.get("id") == cid), None)
        if found_idx is not None:
            existing[found_idx] = entry
        else:
            existing.append(entry)

        current["citas"] = existing
        current["total_citas"] = len(existing)
        current["fecha_actualizacion"] = datetime.now().isoformat()

        try:
            with open(citas_path, 'w', encoding='utf-8') as f:
                json.dump(current, f, indent=2, ensure_ascii=False)
            return {"success": True, "ok": True, "cita": entry, "library_citations": current, "archivo_json": f"{lid}.json"}
        except Exception as e:
            return {"error": f"Error guardando {lid}.json: {e}"}

    def delete_library_citation(self, lib_id: str, citation_id: str) -> Dict[str, Any]:
        current = self.get_library_citations(lib_id)
        lid = current.get("libreria", lib_id.lower())
        citas_path = os.path.join(self.librerias_dir, f"{lid}.json")

        existing = current.get("citas", [])
        initial_len = len(existing)
        existing = [c for c in existing if c.get("id") != citation_id]

        if len(existing) == initial_len:
            return {"error": f"Cita no encontrada: {citation_id}"}

        current["citas"] = existing
        current["total_citas"] = len(existing)
        current["fecha_actualizacion"] = datetime.now().isoformat()

        try:
            with open(citas_path, 'w', encoding='utf-8') as f:
                json.dump(current, f, indent=2, ensure_ascii=False)
            return {"success": True, "ok": True, "deleted_id": citation_id, "total_citas": len(existing)}
        except Exception as e:
            return {"error": f"Error guardando cambios en {lid}.json: {e}"}

    def export_library_citations(self, lib_id: str, workspace_path: str) -> Dict[str, Any]:
        current = self.get_library_citations(lib_id)
        lid = current.get("libreria", lib_id.lower())
        src_path = os.path.join(self.librerias_dir, f"{lid}.json")

        if not os.path.exists(src_path):
            return {"error": f"No hay archivo de citas para la librería {lib_id}"}

        dest_dir = os.path.abspath(workspace_path)
        os.makedirs(dest_dir, exist_ok=True)
        dest_file = os.path.join(dest_dir, f"{lid}.json")

        try:
            shutil.copy2(src_path, dest_file)
            return {
                "success": True,
                "ok": True,
                "exported_to": dest_file,
                "filename": f"{lid}.json",
                "total_citas": current.get("total_citas", 0)
            }
        except Exception as e:
            return {"error": f"Error exportando al proyecto: {e}"}

    def analyze_library_topic(self, lib_id: str, topic_or_func: str, ai_engine, model: str = "qwen2.5-coder:7b") -> Dict[str, Any]:
        """ Analiza el uso de una función o módulo de la librería para generar una ficha técnica estructurada """
        all_libs = {l["id"]: l for l in self.list_libraries()}
        meta = all_libs.get(lib_id.lower()) or {"nombre": lib_id, "repo": lib_id}
        lib_name = meta.get("nombre", lib_id)

        prompt = (
            f"Analiza técnicamente la función, clase o módulo '{topic_or_func}' de la librería '{lib_name}' (Python).\n"
            f"Proporciona la sintaxis moderna oficial, explicación técnica concisa, parámetros cruciales, y un snippet de código Python limpio, probado y ejecutable.\n\n"
            "DEVUELVE EXCLUSIVAMENTE UN OBJETO JSON VÁLIDO con esta estructura exacta:\n"
            "{\n"
            f'  "tema": "Nombre descriptivo del caso de uso",\n'
            f'  "modulo": "{lib_id}",\n'
            f'  "funcion": "{topic_or_func}",\n'
            '  "snippet": "# Código Python ejecutable de ejemplo\\nimport ...",\n'
            '  "explicacion": "Explicación técnica en 2-3 frases de qué hace, por qué se usa y qué devuelve.",\n'
            '  "parametros_clave": ["param1", "param2", "param3"],\n'
            '  "tags": ["tag1", "tag2", "tag3"]\n'
            "}\n"
        )

        sys_prompt = "Eres un Desarrollador Senior y Analista de APIs de Python. Devuelve ÚNICAMENTE un objeto JSON válido sin texto ni explicaciones adicionales."

        try:
            accum = ""
            for chunk in ai_engine.generate_response(prompt, model=model, system_prompt=sys_prompt):
                accum += chunk

            clean = accum.strip()
            if "```" in clean:
                s = clean.find('{')
                e = clean.rfind('}')
                if s != -1 and e != -1:
                    clean = clean[s:e+1]

            data = json.loads(clean)
            return {"success": True, "analysis": data}
        except Exception as e:
            return {"error": f"Error analizando {topic_or_func} con IA: {e}"}

    def get_all_library_citations_for_ai(self, query: Optional[str] = None, max_results: int = 10) -> List[Dict[str, Any]]:
        """ Recolecta citas de librerías para alimentar el razonamiento de los modelos en el chat """
        results = []
        if not os.path.isdir(self.librerias_dir):
            return []

        q_terms = [t.lower() for t in (query or "").split() if len(t) > 2]

        for fname in os.listdir(self.librerias_dir):
            if not fname.endswith(".json") or fname == "lista_librerias.json":
                continue
            fpath = os.path.join(self.librerias_dir, fname)
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    lib_data = json.load(f)
                lname = lib_data.get("nombre") or lib_data.get("libreria") or fname
                for c in lib_data.get("citas", []):
                    item = {
                        "tipo": "libreria",
                        "libreria": lname,
                        "modulo": c.get("modulo", ""),
                        "funcion": c.get("funcion", ""),
                        "tema": c.get("tema", ""),
                        "snippet": c.get("snippet", ""),
                        "explicacion": c.get("explicacion", ""),
                        "parametros": c.get("parametros_clave", []),
                        "tags": c.get("tags", []),
                        "id": c.get("id", "")
                    }
                    if not q_terms:
                        results.append(item)
                    else:
                        match_count = sum(1 for term in q_terms if term in item["funcion"].lower() or term in item["tema"].lower() or term in item["explicacion"].lower() or term in item["libreria"].lower() or any(term in str(tg).lower() for tg in item["tags"]))
                        if match_count > 0:
                            item["_score"] = match_count
                            results.append(item)
            except Exception:
                continue

        if q_terms:
            results.sort(key=lambda x: x.get("_score", 0), reverse=True)
        return results[:max_results]
