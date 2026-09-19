"""
Servicio de Papers y Algoritmos Seminales de Machine Learning en Prig IDE.
Permite explorar, buscar localmente y desde GitHub, leer, descargar al workspace
y consultar interactivamente con modelos de IA sobre las 21 monografías algorítmicas.
"""

import os
import json
import shutil
import re
from typing import List, Dict, Any, Optional, Generator

GITHUB_REPO_DEFAULT = "guillermopetcho/Prig-IDE"
GITHUB_BRANCH_DEFAULT = "main"

CATALOGO_21_ALGORITMOS: List[Dict[str, Any]] = [
    {
        "id": "01_regresion_lineal_y_regularizada",
        "num": 1,
        "titulo": "Regresión Lineal y Regularizada (OLS, Ridge, Lasso y Elastic Net)",
        "categoria": "Supervisado / Regresión",
        "icono": "fa-chart-line",
        "color": "#89b4fa",
        "papers_clave": "Legendre (1805), Gauss (1809), Hoerl & Kennard (1970), Tibshirani (1996), Zou & Hastie (2005), Efron (2004)",
        "autores": ["Legendre", "Gauss", "Hoerl", "Kennard", "Tibshirani", "Zou", "Hastie", "Efron"],
        "conceptos": ["OLS", "Ridge", "Lasso", "Elastic Net", "Gauss-Markov", "Soft-Thresholding", "Coordinate Descent", "LARS"],
        "resumen": "Formulación matricial cerrada, regularizaciones L1/L2, efecto de agrupamiento y optimización por descenso por coordenadas."
    },
    {
        "id": "02_regresion_logistica",
        "num": 2,
        "titulo": "Regresión Logística y Modelos Log-Lineales (Logit, Softmax e IRLS)",
        "categoria": "Supervisado / Clasificación",
        "icono": "fa-bezier-curve",
        "color": "#a6e3a1",
        "papers_clave": "Berkson (1944), Cox (1958), Green (1984), McCullagh & Nelder (1989)",
        "autores": ["Berkson", "Cox", "Green", "McCullagh", "Nelder"],
        "conceptos": ["Logit", "Sigmoide", "Cross-Entropy", "IRLS", "Newton-Raphson", "Softmax Multinomial", "Hessiana"],
        "resumen": "Modelado de probabilidades vía odds ratio, convergencia cuadrática mediante mínimos cuadrados reponderados iterativamente (IRLS)."
    },
    {
        "id": "03_arboles_cart_c45",
        "num": 3,
        "titulo": "Árboles de Decisión (CART, ID3 y C4.5)",
        "categoria": "Supervisado / Árboles",
        "icono": "fa-network-wired",
        "color": "#fab387",
        "papers_clave": "Breiman, Friedman, Olshen & Stone (1984), Quinlan (1986, 1993)",
        "autores": ["Breiman", "Friedman", "Olshen", "Stone", "Quinlan"],
        "conceptos": ["Impureza de Gini", "Entropía de Shannon", "Information Gain", "Gain Ratio", "Cost-Complexity Pruning", "Poda Alfa"],
        "resumen": "Partición recursiva del espacio de características, criterios de impureza y poda por complejidad de costo."
    },
    {
        "id": "04_random_forest",
        "num": 4,
        "titulo": "Random Forest y Métodos de Bagging",
        "categoria": "Supervisado / Ensembles",
        "icono": "fa-tree",
        "color": "#a6adc8",
        "papers_clave": "Leo Breiman (1996, 2001), Tin Kam Ho (1995, 1998), Amit & Geman (1997)",
        "autores": ["Breiman", "Ho", "Amit", "Geman"],
        "conceptos": ["Bagging", "Bootstrap", "Random Subspace", "Reducción de Varianza", "Error OOB", "Importancia MDA"],
        "resumen": "Descorrelación de árboles mediante subespacios aleatorios, estimación insesgada Out-Of-Bag y análisis de permutación."
    },
    {
        "id": "05_gradient_boosting_gbm",
        "num": 5,
        "titulo": "Gradient Boosting Machines (GBM y AdaBoost)",
        "categoria": "Supervisado / Ensembles",
        "icono": "fa-stairs",
        "color": "#f9e2af",
        "papers_clave": "Freund & Schapire (1995, 1997), Jerome H. Friedman (2001, 2002), Mason et al. (1999)",
        "autores": ["Freund", "Schapire", "Friedman", "Mason"],
        "conceptos": ["AdaBoost", "Descenso de Gradiente Funcional", "Pseudo-Residuos", "Shrinkage", "Subsampling Estocástico"],
        "resumen": "Optimización numérica en el espacio no paramétrico de funciones guiada por el gradiente negativo de la pérdida."
    },
    {
        "id": "06_xgboost",
        "num": 6,
        "titulo": "XGBoost (Extreme Gradient Boosting)",
        "categoria": "Supervisado / Ensembles",
        "icono": "fa-bolt",
        "color": "#f38ba8",
        "papers_clave": "Tianqi Chen & Carlos Guestrin (2016)",
        "autores": ["Chen", "Guestrin"],
        "conceptos": ["Aproximación de Taylor de 2º Orden", "Gradientes g_i", "Hessianos h_i", "Weighted Quantile Sketch", "Sparsity-Awareness"],
        "resumen": "Expansión cuadrática analítica para pesos óptimos de hoja, manejo nativo de valores faltantes y regularización Gamma/Lambda."
    },
    {
        "id": "07_lightgbm",
        "num": 7,
        "titulo": "LightGBM: Fast Gradient Boosting",
        "categoria": "Supervisado / Ensembles",
        "icono": "fa-feather",
        "color": "#94e2d5",
        "papers_clave": "Guolin Ke, Qi Meng, Thomas Finley, Taifeng Wang, Wei Chen, Weidong Ma, Qiwei Ye, Tie-Yan Liu (2017)",
        "autores": ["Ke", "Meng", "Finley", "Wang", "Chen", "Liu"],
        "conceptos": ["GOSS", "EFB", "Histogramas uint8", "Leaf-Wise con Profundidad Máxima", "Sustracción de Histogramas"],
        "resumen": "Muestreo unilateral basado en gradiente, empaquetamiento de características exclusivas y crecimiento de hoja óptimo 20x más rápido."
    },
    {
        "id": "08_catboost",
        "num": 8,
        "titulo": "CatBoost: Gradient Boosting with Categorical Features",
        "categoria": "Supervisado / Ensembles",
        "icono": "fa-cat",
        "color": "#cba6f7",
        "papers_clave": "Liudmila Prokhorenkova, Gleb Gulin, Aleksandr Vorobev, Anna Veronika Dorogush, Andrey Gulin (2018)",
        "autores": ["Prokhorenkova", "Gulin", "Vorobev", "Dorogush"],
        "conceptos": ["Prediction Shift", "Ordered Boosting", "Ordered Target Statistics", "Oblivious Trees", "Evaluación Bitwise"],
        "resumen": "Prevención formal del sesgo de predicción y target leakage con permutaciones aleatorias y árboles simétricos eficientes."
    },
    {
        "id": "09_svm_y_svr",
        "num": 9,
        "titulo": "Support Vector Machines (SVM y SVR)",
        "categoria": "Supervisado / Margen Máximo",
        "icono": "fa-shapes",
        "color": "#eba0ac",
        "papers_clave": "Vapnik & Chervonenkis (1974), Boser, Guyon & Vapnik (1992), Cortes & Vapnik (1995), Platt (1998)",
        "autores": ["Vapnik", "Chervonenkis", "Boser", "Guyon", "Cortes", "Platt", "Smola"],
        "conceptos": ["Dimensión VC", "Margen Máximo", "Dual de Wolfe", "Condiciones KKT", "Kernel Trick", "SMO", "Tubo Epsilon-SVR"],
        "resumen": "Minimización del Riesgo Estructural, espacios de Hilbert RKHS con kernels RBF y optimizador analítico Sequential Minimal Optimization."
    },
    {
        "id": "10_knn_vecinos_cercanos",
        "num": 10,
        "titulo": "k-Nearest Neighbors (k-NN) y Búsqueda en Espacios Métricos",
        "categoria": "Supervisado / Basado en Instancias",
        "icono": "fa-users-rays",
        "color": "#74c7ec",
        "papers_clave": "Fix & Hodges (1951), Cover & Hart (1967), Bentley (1975), Stone (1977)",
        "autores": ["Fix", "Hodges", "Cover", "Hart", "Bentley", "Stone"],
        "conceptos": ["Teorema de Cover-Hart", "Cota 2*R*", "Consistencia de Stone", "Métrica de Minkowski", "KD-Tree", "Ball-Tree"],
        "resumen": "Aprendizaje no paramétrico perezoso, cota analítica de error asintótico respecto al clasificador bayesiano óptimo y partición espacial."
    },
    {
        "id": "11_naive_bayes",
        "num": 11,
        "titulo": "Clasificador Bayesiano Ingenuo (Naive Bayes)",
        "categoria": "Supervisado / Probabilístico",
        "icono": "fa-square-poll-vertical",
        "color": "#b4befe",
        "papers_clave": "Thomas Bayes (1763), Laplace (1814), Duda & Hart (1973), Domingos & Pazzani (1997)",
        "autores": ["Bayes", "Laplace", "Duda", "Hart", "Domingos", "Pazzani"],
        "conceptos": ["Independencia Condicional", "MAP", "Suavizado de Laplace", "Gaussian NB", "Multinomial NB", "Paradoja de Domingos-Pazzani"],
        "resumen": "Estimación Maximum A Posteriori (MAP), variantes gaussiana/multinomial y prueba de por qué acierta bajo violaciones de independencia."
    },
    {
        "id": "12_kmeans_clustering",
        "num": 12,
        "titulo": "k-Means y k-Means++ Clustering",
        "categoria": "No Supervisado / Particional",
        "icono": "fa-circle-nodes",
        "color": "#89dceb",
        "papers_clave": "Steinhaus (1956), Lloyd (1957/1982), MacQueen (1967), Arthur & Vassilvitskii (2007), Elkan (2003)",
        "autores": ["Steinhaus", "Lloyd", "MacQueen", "Arthur", "Vassilvitskii", "Elkan"],
        "conceptos": ["Inercia Intra-Cluster", "Algoritmo de Lloyd", "Muestreo D(x)^2", "Cota O(log k)", "Desigualdad Triangular de Elkan"],
        "resumen": "Convergencia a óptimos locales de suma de cuadrados residuales, inicialización k-Means++ con cota logarítmica y aceleración Elkan."
    },
    {
        "id": "13_dbscan_clustering",
        "num": 13,
        "titulo": "DBSCAN: Density-Based Spatial Clustering",
        "categoria": "No Supervisado / Densidad",
        "icono": "fa-braille",
        "color": "#fab387",
        "papers_clave": "Martin Ester, Hans-Peter Kriegel, Jörg Sander, Xiaowei Xu (1996), Campello et al. (2013 HDBSCAN)",
        "autores": ["Ester", "Kriegel", "Sander", "Xu", "Campello"],
        "conceptos": ["Epsilon-Vecindad", "MinPts", "Puntos Núcleo", "Puntos Borde", "Ruido", "Densidad-Conectividad", "k-distance Graph"],
        "resumen": "Descubrimiento de clústeres de morfología arbitraria sin fijar k de antemano, con rechazo robusto de valores atípicos."
    },
    {
        "id": "14_gmm_y_algoritmo_em",
        "num": 14,
        "titulo": "Gaussian Mixture Models y Algoritmo Expectation-Maximization (EM)",
        "categoria": "No Supervisado / Probabilístico",
        "icono": "fa-chart-area",
        "color": "#f2cdcd",
        "papers_clave": "Karl Pearson (1894), Dempster, Laird & Rubin (1977), Neal & Hinton (1998)",
        "autores": ["Pearson", "Dempster", "Laird", "Rubin", "Neal", "Hinton"],
        "conceptos": ["Variables Latentes z", "Paso E", "Responsabilidades Gamma", "Paso M", "ELBO", "Descomposición Cholesky", "BIC / AIC"],
        "resumen": "Clustering blando probabilístico mediante maximización monótona de la cota inferior variacional (ELBO) y selección por BIC."
    },
    {
        "id": "15_pca_y_kernel_pca",
        "num": 15,
        "titulo": "Análisis de Componentes Principales (PCA y Kernel PCA)",
        "categoria": "No Supervisado / Reducción Dimensionalidad",
        "icono": "fa-compress",
        "color": "#89b4fa",
        "papers_clave": "Karl Pearson (1901), Harold Hotelling (1933), Eckart & Young (1936), Schölkopf, Smola & Müller (1998)",
        "autores": ["Pearson", "Hotelling", "Eckart", "Young", "Schölkopf", "Smola", "Müller"],
        "conceptos": ["Covarianza Muestral", "Descomposición SVD", "Teorema Eckart-Young", "Varianza Explicada", "Kernel PCA", "Centrado de Gram"],
        "resumen": "Proyección lineal ortogonal que maximiza la varianza y minimiza el error de reconstrucción, con extensión RKHS no lineal."
    },
    {
        "id": "16_tsne_y_umap",
        "num": 16,
        "titulo": "t-SNE y UMAP (Visualización No Lineal de Manifolds)",
        "categoria": "No Supervisado / Variedades",
        "icono": "fa-eye",
        "color": "#a6e3a1",
        "papers_clave": "Hinton & Roweis (2002 SNE), van der Maaten & Hinton (2008 t-SNE), McInnes, Healy & Melville (2018 UMAP)",
        "autores": ["Hinton", "Roweis", "van der Maaten", "McInnes", "Healy", "Melville"],
        "conceptos": ["Problema de Aglomeración", "Distribución t de Student", "Colas Pesadas de Cauchy", "Divergencia KL", "Conjuntos Difusos", "Cross-Entropy Difusa"],
        "resumen": "Preservación probabilística de vecindades locales con corrección de volumen en bajas dimensiones y geometría riemanniana difusa."
    },
    {
        "id": "17_mlp_y_backpropagation",
        "num": 17,
        "titulo": "Perceptrón Multicapa (MLP) y Algoritmo de Backpropagation",
        "categoria": "Deep Learning / Redes Densas",
        "icono": "fa-network-wired",
        "color": "#cba6f7",
        "papers_clave": "Rosenblatt (1958), Minsky & Papert (1969), Rumelhart, Hinton & Williams (1986), Cybenko (1989), Kingma & Ba (2014 Adam)",
        "autores": ["Rosenblatt", "Rumelhart", "Hinton", "Williams", "Cybenko", "Hornik", "Glorot", "He", "Loshchilov"],
        "conceptos": ["Teorema de Aproximación Universal", "Modo Reverso de Diferenciación", "Jacobianos en Cadena", "He Normal", "AdamW Desacoplado"],
        "resumen": "Capacidad de modelado no lineal arbitrario con regla de la cadena reversa O(W) y optimización con momentos adaptativos."
    },
    {
        "id": "18_cnn_y_resnet",
        "num": 18,
        "titulo": "Redes Convolucionales (CNN) y Arquitectura ResNet",
        "categoria": "Deep Learning / Visión por Computadora",
        "icono": "fa-image",
        "color": "#f38ba8",
        "papers_clave": "Fukushima (1980), LeCun et al. (1989/1998 LeNet-5), Krizhevsky et al. (2012 AlexNet), Kaiming He et al. (2016 ResNet)",
        "autores": ["Fukushima", "LeCun", "Krizhevsky", "He", "Zhang", "Ren", "Sun"],
        "conceptos": ["Equivarianza a Traslaciones", "Receptive Field", "Problema de Degradación", "Conexión Residual de Identidad", "Gradient Highway", "im2col"],
        "resumen": "Convolución discreta 2D acelerada con GEMM y aprendizaje de residuos H(x) = F(x) + x permitiendo entrenar redes de más de 1000 capas."
    },
    {
        "id": "19_rnn_lstm_y_gru",
        "num": 19,
        "titulo": "Redes Recurrentes (RNN, LSTM y GRU)",
        "categoria": "Deep Learning / Secuencias",
        "icono": "fa-clock-rotate-left",
        "color": "#fab387",
        "papers_clave": "Elman (1990), Hochreiter & Schmidhuber (1997 LSTM), Gers et al. (2000), Cho et al. (2014 GRU)",
        "autores": ["Elman", "Hochreiter", "Schmidhuber", "Gers", "Cho", "Bengio", "Jozefowicz"],
        "conceptos": ["BPTT", "Desvanecimiento Exponencial", "Constant Error Carousel (CEC)", "Compuerta de Olvido", "Estado de Celda", "Forget Bias Rule"],
        "resumen": "Protección de gradientes temporales mediante compuertas multiplicativas analógicas y carrusel de error aditivo constante."
    },
    {
        "id": "20_transformer_y_atencion",
        "num": 20,
        "titulo": "Transformers y Mecanismos de Autoatención",
        "categoria": "Deep Learning / Modelos Fundacionales",
        "icono": "fa-arrows-to-eye",
        "color": "#f9e2af",
        "papers_clave": "Vaswani et al. (2017), Ba et al. (2016 LayerNorm), Xiong et al. (2020 Pre-LN), Su et al. (2021 RoPE), Dao et al. (2022 FlashAttention)",
        "autores": ["Vaswani", "Shazeer", "Bahdanau", "Luong", "Xiong", "Su", "Dao"],
        "conceptos": ["Scaled Dot-Product", "Multi-Head Attention", "Varianza Unitaria 1/sqrt(d_k)", "RoPE 2D", "Pre-LN", "KV-Cache", "FlashAttention SRAM"],
        "resumen": "Eliminación de la recurrencia con distancia de interacción O(1), atención multicabezal, codificación posicional rotatoria y tiling en SRAM."
    },
    {
        "id": "21_modelos_difusion_ddpm",
        "num": 21,
        "titulo": "Modelos Probabilísticos de Difusión (DDPM, SDE y Latent Diffusion)",
        "categoria": "Deep Learning / Generativo",
        "icono": "fa-wand-magic-sparkles",
        "color": "#eba0ac",
        "papers_clave": "Sohl-Dickstein et al. (2015), Ho, Jain & Abbeel (2020 DDPM), Song et al. (2020 SDE/DDIM), Rombach et al. (2022 Stable Diffusion)",
        "autores": ["Sohl-Dickstein", "Ho", "Jain", "Abbeel", "Song", "Nichol", "Dhariwal", "Rombach"],
        "conceptos": ["Cadena Markoviana Forward", "Salto Analítico q(x_t|x_0)", "Posterior Tratable", "L_simple MSE", "Score Matching", "Langevin", "Latent Diffusion"],
        "resumen": "Inversión termodinámica de perturbaciones gaussianas infinitesimales con salto analítico cerrado y estimación de ruido equivalente a score SDE."
    }
]


class PapersService:
    """Gestiona el catálogo, búsqueda, lectura y consulta de papers seminales de ML."""

    def __init__(self, base_dir: Optional[str] = None):
        if base_dir:
            self.base_dir = os.path.abspath(base_dir)
        else:
            # Buscar el directorio raíz de Prig
            current = os.path.dirname(os.path.abspath(__file__))
            self.base_dir = os.path.abspath(os.path.join(current, ".."))

        self.docs_dir = os.path.join(self.base_dir, "docs")
        self.algoritmos_dir = os.path.join(self.docs_dir, "algoritmos_ml")
        self.analisis_dir = os.path.join(self.docs_dir, "analisis_papers")
        self.compendio_path = os.path.join(self.docs_dir, "papers_machine_learning_referencias.md")
        self.catalogo = CATALOGO_21_ALGORITMOS

    def list_papers(self, q: Optional[str] = None, categoria: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lista las monografías con metadatos, estado de archivos locales y filtrado."""
        results = []
        q_clean = (q or "").strip().lower()
        cat_clean = (categoria or "").strip().lower()

        for item in self.catalogo:
            # Comprobar existencia y tamaños en disco
            ficha_path = os.path.join(self.algoritmos_dir, f"{item['id']}.md")
            analisis_path = os.path.join(self.analisis_dir, f"{item['id']}.md")

            ficha_existe = os.path.isfile(ficha_path)
            analisis_existe = os.path.isfile(analisis_path)

            ficha_bytes = os.path.getsize(ficha_path) if ficha_existe else 0
            analisis_bytes = os.path.getsize(analisis_path) if analisis_existe else 0

            entry = {
                **item,
                "ficha_existe": ficha_existe,
                "analisis_existe": analisis_existe,
                "ficha_bytes": ficha_bytes,
                "analisis_bytes": analisis_bytes,
                "github_url_ficha": f"https://github.com/{GITHUB_REPO_DEFAULT}/blob/{GITHUB_BRANCH_DEFAULT}/docs/algoritmos_ml/{item['id']}.md",
                "github_url_analisis": f"https://github.com/{GITHUB_REPO_DEFAULT}/blob/{GITHUB_BRANCH_DEFAULT}/docs/analisis_papers/{item['id']}.md",
                "github_raw_analisis": f"https://raw.githubusercontent.com/{GITHUB_REPO_DEFAULT}/{GITHUB_BRANCH_DEFAULT}/docs/analisis_papers/{item['id']}.md"
            }

            # Filtro por categoría
            if cat_clean and cat_clean != "todas":
                if cat_clean not in entry["categoria"].lower():
                    continue

            # Filtro por consulta textual
            if q_clean:
                texto_busqueda = (
                    f"{entry['titulo']} {entry['categoria']} {entry['papers_clave']} "
                    f"{' '.join(entry['autores'])} {' '.join(entry['conceptos'])} {entry['resumen']}"
                ).lower()
                
                # Búsqueda por términos
                terminos = [t for t in q_clean.split() if t]
                if not all(t in texto_busqueda for t in terminos):
                    # Si no coincide en metadatos, buscar en contenido si existe
                    coincide_en_archivo = False
                    if analisis_existe:
                        try:
                            with open(analisis_path, "r", encoding="utf-8") as f:
                                contenido_doc = f.read(50000).lower()
                                if all(t in contenido_doc for t in terminos):
                                    coincide_en_archivo = True
                        except Exception:
                            pass
                    if not coincide_en_archivo:
                        continue

            results.append(entry)

        return results

    def get_paper(self, paper_id: str, tipo: str = "analisis") -> Dict[str, Any]:
        """Obtiene el contenido completo en Markdown y metadatos de un paper/algoritmo."""
        # Sanitizar identificador
        clean_id = os.path.basename(paper_id).replace(".md", "")
        
        # Buscar en catálogo
        meta = next((item for item in self.catalogo if item["id"] == clean_id), None)
        if not meta:
            # Fallback por número o búsqueda aproximada
            if clean_id.isdigit():
                num = int(clean_id)
                meta = next((item for item in self.catalogo if item["num"] == num), None)

        target_dir = self.analisis_dir if tipo == "analisis" else self.algoritmos_dir
        filename = f"{clean_id}.md" if not clean_id.endswith(".md") else clean_id
        file_path = os.path.join(target_dir, filename)

        if not os.path.isfile(file_path):
            return {"error": f"No se encontró el documento para '{paper_id}' (tipo: {tipo})"}

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                contenido = f.read()

            rel_path = os.path.relpath(file_path, self.base_dir)
            github_url = f"https://github.com/{GITHUB_REPO_DEFAULT}/blob/{GITHUB_BRANCH_DEFAULT}/{rel_path}"

            return {
                "success": True,
                "id": clean_id,
                "tipo": tipo,
                "titulo": (meta["titulo"] if meta else clean_id),
                "categoria": (meta["categoria"] if meta else "Algoritmo ML"),
                "meta": meta,
                "contenido": contenido,
                "tamano_bytes": len(contenido.encode("utf-8")),
                "lineas": len(contenido.splitlines()),
                "archivo_relativo": rel_path,
                "github_url": github_url,
                "github_repo": GITHUB_REPO_DEFAULT
            }
        except Exception as e:
            return {"error": f"Error leyendo archivo de paper: {str(e)}"}

    def download_paper(self, paper_id: str, workspace_path: str, tipo: str = "analisis") -> Dict[str, Any]:
        """Descarga o copia el archivo Markdown directamente a la carpeta del proyecto del usuario."""
        paper = self.get_paper(paper_id, tipo=tipo)
        if "error" in paper:
            return paper

        dest_folder = os.path.join(workspace_path, "papers_ml")
        os.makedirs(dest_folder, exist_ok=True)

        target_filename = f"{paper['id']}_{tipo}.md"
        dest_path = os.path.join(dest_folder, target_filename)

        try:
            with open(dest_path, "w", encoding="utf-8") as f:
                f.write(paper["contenido"])

            rel_dest = os.path.relpath(dest_path, workspace_path)
            return {
                "success": True,
                "ok": True,
                "saved_to": dest_path,
                "rel_path": rel_dest,
                "filename": target_filename,
                "bytes": len(paper["contenido"].encode("utf-8")),
                "mensaje": f"Monografía guardada exitosamente en {rel_dest}"
            }
        except Exception as e:
            return {"error": f"Error al guardar monografía en el proyecto: {str(e)}"}

    def ask_paper_stream(
        self,
        paper_id: str,
        pregunta: str,
        ai_engine,
        modelo: str = "qwen2.5-coder:7b",
        tipo: str = "analisis",
        historial: Optional[List[Dict[str, str]]] = None
    ) -> Generator[str, None, None]:
        """Inyecta el contenido del paper y responde preguntas con el modelo de IA seleccionado."""
        doc = self.get_paper(paper_id, tipo=tipo)
        contenido = doc.get("contenido", "")
        titulo = doc.get("titulo", paper_id)

        # Contexto estructurado enfocado (primeras 20,000 letras para no desbordar el contexto)
        contexto_paper = contenido[:22000] if len(contenido) > 22000 else contenido

        sys_prompt = (
            "Eres un Catedrático y Tutor Senior de Inteligencia Artificial y Machine Learning en Prig IDE. "
            f"Estás analizando la monografía del paper seminal '{titulo}'. "
            "Responde a las preguntas del desarrollador o estudiante con máximo rigor matemático, claridad didáctica, "
            "fórmulas en LaTeX (usando $ o $$) y ejemplos de código en Python/NumPy cuando sea oportuno. "
            "Basa tus explicaciones y deducciones estrictamente en el contenido y derivaciones de la monografía proporcionada."
        )

        historial_str = ""
        if historial:
            mensajes_recientes = historial[-6:]
            for m in mensajes_recientes:
                rol = "Alumno" if m.get("rol") in ("user", "usuario") else "Profesor"
                historial_str += f"\n{rol}: {m.get('texto', '')}"

        user_prompt = (
            f"=== DOCUMENTO SEMINAL: {titulo} ===\n\n"
            f"{contexto_paper}\n\n"
            f"=== FIN DEL DOCUMENTO ===\n"
            f"{historial_str}\n\n"
            f"Pregunta del Alumno: {pregunta}\n\n"
            "Profesor:"
        )

        try:
            for chunk in ai_engine.generate_response(user_prompt, model=modelo, system_prompt=sys_prompt, uso="tutor_papers"):
                yield chunk
        except Exception as e:
            yield f"\n[Error consultando al modelo {modelo}: {str(e)}]"

