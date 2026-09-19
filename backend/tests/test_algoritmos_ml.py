"""
Pruebas de verificación para el Compendio de Papers ML, Monografías Algorítmicas
y el Sistema Modular de Diagramas de Machine Learning / Deep Learning.
"""

import os
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCS_DIR = os.path.join(RAIZ, "docs")
ALGORITMOS_DIR = os.path.join(DOCS_DIR, "algoritmos_ml")
PAPERS_FILE = os.path.join(DOCS_DIR, "papers_machine_learning_referencias.md")
KAGGLE_BACKEND_FILE = os.path.join(RAIZ, "backend", "kaggle_lector.py")
DIAGRAMAS_JS_FILE = os.path.join(RAIZ, "frontend", "js", "diagramas_ml.js")
KAGGLE_JS_FILE = os.path.join(RAIZ, "frontend", "js", "kaggle_lector.js")


class TestCompendioYMonografiasML(unittest.TestCase):
    """Verifica la integridad del compendio de papers y las 21 monografías de algoritmos."""

    def test_compendio_papers_existe_y_completo(self):
        """Verifica que el archivo de compendio de papers exista y contenga las familias principales."""
        self.assertTrue(os.path.exists(PAPERS_FILE), f"Falta {PAPERS_FILE}")
        with open(PAPERS_FILE, "r", encoding="utf-8") as f:
            contenido = f.read()

        # Debe tener más de 10 KB de texto con rigor matemático y bibliográfico
        self.assertGreater(len(contenido), 10000)

        familias_clave = [
            "Modelos Lineales y Regularizados",
            "Máquinas de Vectores de Soporte (SVM y SVR)",
            "Árboles de Decisión y Ensambles",
            "Métodos Basados en Instancias (k-NN)",
            "Modelos Probabilísticos y Bayesianos",
            "Agrupamiento y Aprendizaje No Supervisado",
            "Reducción de Dimensionalidad y Variedades",
            "Deep Learning Clásico y Redes Neuronales",
            "Transformers, Autoatención y Modelos Fundacionales",
            "Modelos Generativos y Difusión",
        ]
        for familia in familias_clave:
            self.assertIn(familia, contenido, f"Falta la familia '{familia}' en el compendio")

        # Verificar presencia de citas canónicas clave
        citas_clave = ["Hoerl", "Tibshirani", "Breiman", "Friedman", "Chen", "Vaswani", "Ho"]
        for cita in citas_clave:
            self.assertIn(cita, contenido, f"Falta la cita seminal de '{cita}' en el compendio")

    def test_21_monografias_existen_y_estructuradas(self):
        """Verifica que las 21 monografías algorítmicas existan y tengan el estándar de 4 bloques."""
        monografias_esperadas = [
            "01_regresion_lineal_y_regularizada.md",
            "02_regresion_logistica.md",
            "03_arboles_cart_c45.md",
            "04_random_forest.md",
            "05_gradient_boosting_gbm.md",
            "06_xgboost.md",
            "07_lightgbm.md",
            "08_catboost.md",
            "09_svm_y_svr.md",
            "10_knn_vecinos_cercanos.md",
            "11_naive_bayes.md",
            "12_kmeans_clustering.md",
            "13_dbscan_clustering.md",
            "14_gmm_y_algoritmo_em.md",
            "15_pca_y_kernel_pca.md",
            "16_tsne_y_umap.md",
            "17_mlp_y_backpropagation.md",
            "18_cnn_y_resnet.md",
            "19_rnn_lstm_y_gru.md",
            "20_transformer_y_atencion.md",
            "21_modelos_difusion_ddpm.md",
        ]

        self.assertTrue(os.path.isdir(ALGORITMOS_DIR), f"No existe el directorio {ALGORITMOS_DIR}")

        secciones_requeridas = [
            "formulación matemática",
            "descomposición modular",
            "diagrama de flujo modular",
            "hiperparámetros",
            "python",
        ]

        for nombre_archivo in monografias_esperadas:
            ruta = os.path.join(ALGORITMOS_DIR, nombre_archivo)
            self.assertTrue(os.path.exists(ruta), f"Falta la monografía: {nombre_archivo}")

            with open(ruta, "r", encoding="utf-8") as f:
                texto = f.read()

            self.assertGreater(
                len(texto),
                2000,
                f"La monografía {nombre_archivo} es muy corta ({len(texto)} caracteres)"
            )

            # Verificar secciones estructurales
            for seccion in secciones_requeridas:
                self.assertIn(
                    seccion,
                    texto.lower(),
                    f"Falta la sección '{seccion}' en {nombre_archivo}"
                )

            # Verificar que contenga al menos un bloque Mermaid válido
            self.assertIn("```mermaid", texto, f"Falta bloque Mermaid en {nombre_archivo}")
            self.assertTrue(
                ("graph TD" in texto or "flowchart TD" in texto or "graph LR" in texto or "flowchart LR" in texto),
                f"El diagrama Mermaid en {nombre_archivo} debe declarar graph o flowchart"
            )

            # Verificar presencia de formulación matemática en LaTeX
            self.assertTrue(
                ("$" in texto or "\\" in texto),
                f"Falta notación matemática en {nombre_archivo}"
            )


class TestIntegracionModularKaggle(unittest.TestCase):
    """Verifica que el backend y frontend de Kaggle y Diagramas estén integrados."""

    def test_backend_prompts_diagramas(self):
        """Verifica que kaggle_lector.py instruya a la IA a generar diagramas Mermaid modulares."""
        with open(KAGGLE_BACKEND_FILE, "r", encoding="utf-8") as f:
            codigo_py = f.read()

        self.assertIn("Diagrama del Algoritmo", codigo_py)
        self.assertIn("```mermaid", codigo_py)
        self.assertIn("4 bloques", codigo_py)

    def test_frontend_diagramas_ml_arquetipos(self):
        """Verifica que diagramas_ml.js posea las 14 plantillas y el puente interactivo."""
        with open(DIAGRAMAS_JS_FILE, "r", encoding="utf-8") as f:
            codigo_js = f.read()

        arquetipos_esperados = [
            "pipeline_ml",
            "xgboost",
            "lightgbm",
            "catboost",
            "random_forest",
            "svm",
            "kmeans",
            "pca",
            "mlp_dl",
            "resnet",
            "transformer_nlp",
            "diffusion",
            "bucle_entrenamiento",
            "modular",
        ]
        for arq in arquetipos_esperados:
            self.assertIn(f"'{arq}'", codigo_js, f"Falta la plantilla '{arq}' en diagramas_ml.js")

        # Verificar función puente
        self.assertIn("window.abrirDiagramaEnModular", codigo_js)

    def test_frontend_kaggle_renderiza_diagramas(self):
        """Verifica que kaggle_lector.js detecte Mermaid y brinde botón de apertura en graficador."""
        with open(KAGGLE_JS_FILE, "r", encoding="utf-8") as f:
            codigo_js = f.read()

        self.assertIn("mermaid", codigo_js)
        self.assertIn("abrirDiagramaEnModular", codigo_js)
        self.assertIn("Abrir en Graficador Modular", codigo_js)


class TestAnalisisPapersSeminales(unittest.TestCase):
    """Verifica la integridad de las monografías de análisis profundo de papers."""

    def test_monografia_01_analisis_papers(self):
        """Verifica que el análisis de papers de la monografía 01 exista y sea riguroso."""
        ruta_01 = os.path.join(DOCS_DIR, "analisis_papers", "01_regresion_lineal_y_regularizada.md")
        self.assertTrue(os.path.exists(ruta_01), f"Falta el archivo: {ruta_01}")

        with open(ruta_01, "r", encoding="utf-8") as f:
            contenido = f.read()

        # Debe tener más de 20 KB de análisis técnico exhaustivo
        self.assertGreater(len(contenido), 20000)

        # Autores y papers seminales
        self.assertIn("Hoerl & Kennard", contenido)
        self.assertIn("Tibshirani", contenido)
        self.assertIn("Zou & Hastie", contenido)
        self.assertIn("Efron", contenido)
        self.assertIn("Friedman", contenido)

        # Teoremas y conceptos matemáticos clave
        conceptos_clave = [
            "Teorema de Gauss-Markov",
            "Teorema de Existencia",
            "Ridge Trace",
            "Soft-Thresholding",
            "Grouping Effect",
            "Double Shrinkage",
            "Descenso por Coordenadas",
        ]
        for c in conceptos_clave:
            self.assertIn(c, contenido, f"Falta concepto '{c}' en la monografía 01 de papers")

        # Código de referencia en Python
        self.assertIn("soft_thresholding", contenido)
        self.assertIn("resolver_elastic_net", contenido)
        self.assertIn("Double Shrinkage", contenido)

    def test_monografia_02_analisis_papers(self):
        """Verifica que el análisis de papers de la monografía 02 exista y sea riguroso."""
        ruta_02 = os.path.join(DOCS_DIR, "analisis_papers", "02_regresion_logistica.md")
        self.assertTrue(os.path.exists(ruta_02), f"Falta el archivo: {ruta_02}")

        with open(ruta_02, "r", encoding="utf-8") as f:
            contenido = f.read()

        # Debe tener más de 20 KB de análisis técnico exhaustivo
        self.assertGreater(len(contenido), 20000)

        # Autores y papers seminales
        self.assertIn("David R. Cox", contenido)
        self.assertIn("Verhulst", contenido)
        self.assertIn("Nelder", contenido)
        self.assertIn("McFadden", contenido)
        self.assertIn("Nocedal", contenido)
        self.assertIn("Albert & Anderson", contenido)

        # Teoremas y conceptos matemáticos clave
        conceptos_clave = [
            "Transformación Logit",
            "Entropía Cruzada Binaria",
            "Matriz Hessiana",
            "Convexidad Estricta",
            "IRLS",
            "Softmax",
            "L-BFGS",
            "Separabilidad Perfecta",
        ]
        for c in conceptos_clave:
            self.assertIn(c, contenido, f"Falta concepto '{c}' en la monografía 02 de papers")

        # Código de referencia en Python
        self.assertIn("sigmoide_estable", contenido)
        self.assertIn("entrenar_regresion_logistica_irls", contenido)

    def test_monografia_03_analisis_papers(self):
        """Verifica que el análisis de papers de la monografía 03 exista y sea riguroso."""
        ruta_03 = os.path.join(DOCS_DIR, "analisis_papers", "03_arboles_cart_c45.md")
        self.assertTrue(os.path.exists(ruta_03), f"Falta el archivo: {ruta_03}")

        with open(ruta_03, "r", encoding="utf-8") as f:
            contenido = f.read()

        # Debe tener más de 20 KB de análisis técnico exhaustivo
        self.assertGreater(len(contenido), 20000)

        # Autores y papers seminales
        self.assertIn("Breiman", contenido)
        self.assertIn("Friedman", contenido)
        self.assertIn("Quinlan", contenido)
        self.assertIn("Morgan", contenido)
        self.assertIn("Sonquist", contenido)

        # Teoremas y conceptos matemáticos clave
        conceptos_clave = [
            "Impureza de Gini",
            "Entropía de Shannon",
            "Gain Ratio",
            "Poda de Complejidad de Coste",
            "eslabón más débil",
            "Variables Sustitutas",
            "1-SE",
        ]
        for c in conceptos_clave:
            self.assertIn(c.lower(), contenido.lower(), f"Falta concepto '{c}' en la monografía 03 de papers")

        # Código de referencia en Python
        self.assertIn("ArbolDecisionCART", contenido)
        self.assertIn("calcular_impureza_gini", contenido)
        self.assertIn("mejor_division_cart", contenido)

    def test_monografia_04_analisis_papers(self):
        """Verifica que el análisis de papers de la monografía 04 exista y sea riguroso."""
        ruta_04 = os.path.join(DOCS_DIR, "analisis_papers", "04_random_forest.md")
        self.assertTrue(os.path.exists(ruta_04), f"Falta el archivo: {ruta_04}")

        with open(ruta_04, "r", encoding="utf-8") as f:
            contenido = f.read()

        # Debe tener más de 20 KB de análisis técnico exhaustivo
        self.assertGreater(len(contenido), 20000)

        # Autores y papers seminales
        self.assertIn("Breiman", contenido)
        self.assertIn("Tin Kam Ho", contenido)
        self.assertIn("Geurts", contenido)

        # Teoremas y conceptos matemáticos clave
        conceptos_clave = [
            "Bagging",
            "Random Subspace",
            "Varianza del Ensamble",
            "Out-Of-Bag",
            "OOB",
            "Permutation Importance",
            "MDA",
            "MDI",
            "Extra-Trees",
        ]
        for c in conceptos_clave:
            self.assertIn(c.lower(), contenido.lower(), f"Falta concepto '{c}' en la monografía 04 de papers")

        # Código de referencia en Python
        self.assertIn("RandomForestClasificador", contenido)
        self.assertIn("mejor_corte_rf", contenido)
        self.assertIn("oob_score_", contenido)
        self.assertIn("permutation_importance_mda", contenido)

    def test_monografia_05_analisis_papers(self):
        """Verifica que el análisis de papers de la monografía 05 exista y sea riguroso."""
        ruta_05 = os.path.join(DOCS_DIR, "analisis_papers", "05_gradient_boosting_gbm.md")
        self.assertTrue(os.path.exists(ruta_05), f"Falta el archivo: {ruta_05}")

        with open(ruta_05, "r", encoding="utf-8") as f:
            contenido = f.read()

        # Debe tener más de 20 KB de análisis técnico exhaustivo
        self.assertGreater(len(contenido), 20000)

        # Autores y papers seminales
        self.assertIn("Friedman", contenido)
        self.assertIn("Schapire", contenido)
        self.assertIn("Freund", contenido)
        self.assertIn("Mason", contenido)

        # Teoremas y conceptos matemáticos clave
        conceptos_clave = [
            "Pseudo-Residuos",
            "Espacio de Funciones",
            "Shrinkage",
            "AdaBoost",
            "Stochastic Gradient Boosting",
            "Pérdida de Huber",
        ]
        for c in conceptos_clave:
            self.assertIn(c.lower(), contenido.lower(), f"Falta concepto '{c}' en la monografía 05 de papers")

        # Código de referencia en Python
        self.assertIn("GradientBoostingClasificador", contenido)
        self.assertIn("construir_arbol_gbm", contenido)
        self.assertIn("mejor_corte_mse", contenido)

    def test_monografia_06_analisis_papers(self):
        """Verifica que el análisis de papers de la monografía 06 exista y sea riguroso."""
        ruta_06 = os.path.join(DOCS_DIR, "analisis_papers", "06_xgboost.md")
        self.assertTrue(os.path.exists(ruta_06), f"Falta el archivo: {ruta_06}")

        with open(ruta_06, "r", encoding="utf-8") as f:
            contenido = f.read()

        # Debe tener más de 20 KB de análisis técnico exhaustivo
        self.assertGreater(len(contenido), 20000)

        # Autores y papers seminales
        self.assertIn("Tianqi Chen", contenido)
        self.assertIn("Carlos Guestrin", contenido)

        # Teoremas y conceptos matemáticos clave
        conceptos_clave = [
            "Expansión en Serie de Taylor de Segundo Orden",
            "Split Gain",
            "Sparsity-Aware",
            "Weighted Quantile Sketch",
            "Column Block Structure",
        ]
        for c in conceptos_clave:
            self.assertIn(c.lower(), contenido.lower(), f"Falta concepto '{c}' en la monografía 06 de papers")

        # Código de referencia en Python
        self.assertIn("XGBoostClasificador", contenido)
        self.assertIn("mejor_corte_xgboost_sparsity", contenido)
        self.assertIn("calcular_gradientes_logloss", contenido)


    def test_monografia_07_analisis_papers(self):
        """Verifica que el análisis de papers de la monografía 07 (LightGBM) exista y sea riguroso."""
        ruta_07 = os.path.join(DOCS_DIR, "analisis_papers", "07_lightgbm.md")
        self.assertTrue(os.path.exists(ruta_07), f"Falta el archivo: {ruta_07}")

        with open(ruta_07, "r", encoding="utf-8") as f:
            contenido = f.read()

        # Debe tener más de 20 KB de análisis técnico exhaustivo
        self.assertGreater(len(contenido), 20000)

        # Autores y papers seminales
        self.assertIn("Guolin Ke", contenido)
        self.assertIn("Qi Meng", contenido)
        self.assertIn("Tie-Yan Liu", contenido)

        # Teoremas y conceptos matemáticos clave
        conceptos_clave = [
            "GOSS",
            "Gradient-based One-Side Sampling",
            "EFB",
            "Exclusive Feature Bundling",
            "Leaf-Wise",
            "Histograma",
            "uint8",
            "Fisher",
        ]
        for c in conceptos_clave:
            self.assertIn(c.lower(), contenido.lower(), f"Falta concepto '{c}' en la monografía 07 de papers")

        # Código de referencia en Python
        self.assertIn("discretizar_en_histograma_uint8", contenido)
        self.assertIn("aplicar_muestreo_goss", contenido)
        self.assertIn("evaluar_division_histograma", contenido)
        self.assertIn("ArbolLeafWiseLightGBM", contenido)


    def test_monografia_08_analisis_papers(self):
        """Verifica que el análisis de papers de la monografía 08 (CatBoost) exista y sea riguroso."""
        ruta_08 = os.path.join(DOCS_DIR, "analisis_papers", "08_catboost.md")
        self.assertTrue(os.path.exists(ruta_08), f"Falta el archivo: {ruta_08}")

        with open(ruta_08, "r", encoding="utf-8") as f:
            contenido = f.read()

        # Debe tener más de 20 KB de análisis técnico exhaustivo
        self.assertGreater(len(contenido), 20000)

        # Autores y papers seminales
        self.assertIn("Prokhorenkova", contenido)
        self.assertIn("Dorogush", contenido)
        self.assertIn("Gulin", contenido)

        # Teoremas y conceptos matemáticos clave
        conceptos_clave = [
            "Prediction Shift",
            "Target Leakage",
            "Ordered Target Statistics",
            "Ordered Boosting",
            "Oblivious Trees",
            "Bitwise",
            "Cross-Features",
        ]
        for c in conceptos_clave:
            self.assertIn(c.lower(), contenido.lower(), f"Falta concepto '{c}' en la monografía 08 de papers")

        # Código de referencia en Python
        self.assertIn("CodificadorOrderedTargetStatistics", contenido)
        self.assertIn("ArbolObliviousRegressor", contenido)


    def test_monografia_09_analisis_papers(self):
        """Verifica que el análisis de papers de la monografía 09 (SVM y SVR) exista y sea riguroso."""
        ruta_09 = os.path.join(DOCS_DIR, "analisis_papers", "09_svm_y_svr.md")
        self.assertTrue(os.path.exists(ruta_09), f"Falta el archivo: {ruta_09}")

        with open(ruta_09, "r", encoding="utf-8") as f:
            contenido = f.read()

        # Debe tener más de 20 KB de análisis técnico exhaustivo
        self.assertGreater(len(contenido), 20000)

        # Autores y papers seminales
        self.assertIn("Vapnik", contenido)
        self.assertIn("Cortes", contenido)
        self.assertIn("Boser", contenido)
        self.assertIn("Smola", contenido)
        self.assertIn("Platt", contenido)

        # Teoremas y conceptos matemáticos clave
        conceptos_clave = [
            "Dimensión VC",
            "Margen",
            "Dual de Wolfe",
            "KKT",
            "Mercer",
            "Sequential Minimal Optimization",
            "SVR",
        ]
        for c in conceptos_clave:
            self.assertIn(c.lower(), contenido.lower(), f"Falta concepto '{c}' en la monografía 09 de papers")

        # Código de referencia en Python
        self.assertIn("SVM_SMO", contenido)
        self.assertIn("_computar_kernel", contenido)


    def test_monografia_10_analisis_papers(self):
        """Verifica que el análisis de papers de la monografía 10 (k-NN) exista y sea riguroso."""
        ruta_10 = os.path.join(DOCS_DIR, "analisis_papers", "10_knn_vecinos_cercanos.md")
        self.assertTrue(os.path.exists(ruta_10), f"Falta el archivo: {ruta_10}")

        with open(ruta_10, "r", encoding="utf-8") as f:
            contenido = f.read()

        # Debe tener más de 20 KB de análisis técnico exhaustivo
        self.assertGreater(len(contenido), 20000)

        # Autores y papers seminales
        self.assertIn("Cover", contenido)
        self.assertIn("Hart", contenido)
        self.assertIn("Fix", contenido)
        self.assertIn("Hodges", contenido)
        self.assertIn("Bentley", contenido)
        self.assertIn("Omohundro", contenido)

        # Teoremas y conceptos matemáticos clave
        conceptos_clave = [
            "Cover",
            "Riesgo de Bayes",
            "Voronoi",
            "Minkowski",
            "KD-Tree",
            "Ball-Tree",
            "Maldición de la Dimensionalidad",
        ]
        for c in conceptos_clave:
            self.assertIn(c.lower(), contenido.lower(), f"Falta concepto '{c}' en la monografía 10 de papers")

        # Código de referencia en Python
        self.assertIn("KDTreePuro", contenido)
        self.assertIn("KNNClasificadorPuro", contenido)


    def test_monografia_11_analisis_papers(self):
        """Verifica que el análisis de papers de la monografía 11 (Naive Bayes) exista y sea riguroso."""
        ruta_11 = os.path.join(DOCS_DIR, "analisis_papers", "11_naive_bayes.md")
        self.assertTrue(os.path.exists(ruta_11), f"Falta el archivo: {ruta_11}")

        with open(ruta_11, "r", encoding="utf-8") as f:
            contenido = f.read()

        # Debe tener más de 20 KB de análisis técnico exhaustivo
        self.assertGreater(len(contenido), 20000)

        # Autores y papers seminales
        self.assertIn("Bayes", contenido)
        self.assertIn("Laplace", contenido)
        self.assertIn("Duda", contenido)
        self.assertIn("Domingos", contenido)
        self.assertIn("Pazzani", contenido)
        self.assertIn("McCallum", contenido)

        # Teoremas y conceptos matemáticos clave
        conceptos_clave = [
            "Independencia Condicional",
            "Maximum A Posteriori",
            "Gaussiano",
            "Multinomial",
            "Bernoulli",
            "Laplace",
            "Domingos",
            "Log-Sum-Exp",
        ]
        for c in conceptos_clave:
            self.assertIn(c.lower(), contenido.lower(), f"Falta concepto '{c}' en la monografía 11 de papers")

        # Código de referencia en Python
        self.assertIn("GaussianNaiveBayesPuro", contenido)
        self.assertIn("MultinomialNaiveBayesPuro", contenido)
        self.assertIn("log_sum_exp", contenido)


    def test_monografia_12_analisis_papers(self):
        """Verifica que el análisis de papers de la monografía 12 (k-Means) exista y sea riguroso."""
        ruta_12 = os.path.join(DOCS_DIR, "analisis_papers", "12_kmeans_clustering.md")
        self.assertTrue(os.path.exists(ruta_12), f"Falta el archivo: {ruta_12}")

        with open(ruta_12, "r", encoding="utf-8") as f:
            contenido = f.read()

        # Debe tener más de 20 KB de análisis técnico exhaustivo
        self.assertGreater(len(contenido), 20000)

        # Autores y papers seminales
        self.assertIn("Lloyd", contenido)
        self.assertIn("MacQueen", contenido)
        self.assertIn("Arthur", contenido)
        self.assertIn("Vassilvitskii", contenido)
        self.assertIn("Elkan", contenido)
        self.assertIn("Rousseeuw", contenido)

        # Teoremas y conceptos matemáticos clave
        conceptos_clave = [
            "Lloyd",
            "Inercia",
            "k-means++",
            "Desigualdad Triangular",
            "Silueta",
            "NP-Hard",
        ]
        for c in conceptos_clave:
            self.assertIn(c.lower(), contenido.lower(), f"Falta concepto '{c}' en la monografía 12 de papers")

        # Código de referencia en Python
        self.assertIn("inicializar_kmeans_plus_plus", contenido)
        self.assertIn("KMeansPuro", contenido)
        self.assertIn("calcular_coeficiente_silueta", contenido)


    def test_monografia_13_analisis_papers(self):
        """Verifica que el análisis de papers de la monografía 13 (DBSCAN) exista y sea riguroso."""
        ruta_13 = os.path.join(DOCS_DIR, "analisis_papers", "13_dbscan_clustering.md")
        self.assertTrue(os.path.exists(ruta_13), f"Falta el archivo: {ruta_13}")

        with open(ruta_13, "r", encoding="utf-8") as f:
            contenido = f.read()

        # Debe tener más de 20 KB de análisis técnico exhaustivo
        self.assertGreater(len(contenido), 20000)

        # Autores y papers seminales
        self.assertIn("Ester", contenido)
        self.assertIn("Kriegel", contenido)
        self.assertIn("Sander", contenido)
        self.assertIn("Xu", contenido)

        # Teoremas y conceptos matemáticos clave
        conceptos_clave = [
            "Vecindario",
            "Punto Núcleo",
            "Alcanzable por Densidad",
            "Conectado por Densidad",
            "Ruido",
            "k-Distancias",
        ]
        for c in conceptos_clave:
            self.assertIn(c.lower(), contenido.lower(), f"Falta concepto '{c}' en la monografía 13 de papers")

        # Código de referencia en Python
        self.assertIn("DBSCANPuro", contenido)
        self.assertIn("_calcular_vecinos", contenido)


    def test_monografia_14_analisis_papers(self):
        """Verifica que el análisis de papers de la monografía 14 (GMM y Algoritmo EM) exista y sea riguroso."""
        ruta_14 = os.path.join(DOCS_DIR, "analisis_papers", "14_gmm_y_algoritmo_em.md")
        self.assertTrue(os.path.exists(ruta_14), f"Falta el archivo: {ruta_14}")

        with open(ruta_14, "r", encoding="utf-8") as f:
            contenido = f.read()

        # Debe tener más de 20 KB de análisis técnico exhaustivo
        self.assertGreater(len(contenido), 20000)

        # Autores y papers seminales
        self.assertIn("Dempster", contenido)
        self.assertIn("Laird", contenido)
        self.assertIn("Rubin", contenido)
        self.assertIn("Bishop", contenido)
        self.assertIn("Schwarz", contenido)

        # Teoremas y conceptos matemáticos clave
        conceptos_clave = [
            "Responsabilidades",
            "Log-Verosimilitud",
            "Paso E",
            "Paso M",
            "ELBO",
            "BIC",
            "AIC",
            "Colapso",
        ]
        for c in conceptos_clave:
            self.assertIn(c.lower(), contenido.lower(), f"Falta concepto '{c}' en la monografía 14 de papers")

        # Código de referencia en Python
        self.assertIn("GMM_EMPuro", contenido)
        self.assertIn("_evaluar_log_gaussiana", contenido)
        self.assertIn("predict_proba", contenido)
        self.assertIn("bic", contenido)


    def test_monografia_15_analisis_papers(self):
        """Verifica que el análisis de papers de la monografía 15 (PCA y Kernel PCA) exista y sea riguroso."""
        ruta_15 = os.path.join(DOCS_DIR, "analisis_papers", "15_pca_y_kernel_pca.md")
        self.assertTrue(os.path.exists(ruta_15), f"Falta el archivo: {ruta_15}")

        with open(ruta_15, "r", encoding="utf-8") as f:
            contenido = f.read()

        # Debe tener más de 20 KB de análisis técnico exhaustivo
        self.assertGreater(len(contenido), 20000)

        # Autores y papers seminales
        self.assertIn("Pearson", contenido)
        self.assertIn("Hotelling", contenido)
        self.assertIn("Eckart", contenido)
        self.assertIn("Young", contenido)
        self.assertIn("Golub", contenido)
        self.assertIn("Schölkopf", contenido)

        # Teoremas y conceptos matemáticos clave
        conceptos_clave = [
            "Varianza",
            "Reconstrucción",
            "Autovectores",
            "SVD",
            "Eckart-Young",
            "Gram",
            "Hilbert",
            "Blanqueamiento",
        ]
        for c in conceptos_clave:
            self.assertIn(c.lower(), contenido.lower(), f"Falta concepto '{c}' en la monografía 15 de papers")

        # Código de referencia en Python
        self.assertIn("PCA_Puro", contenido)
        self.assertIn("KernelPCA_Puro", contenido)
        self.assertIn("explained_variance_ratio_", contenido)
        self.assertIn("_calcular_matriz_kernel", contenido)


    def test_monografia_16_analisis_papers(self):
        """Verifica que el análisis de papers de la monografía 16 (t-SNE y UMAP) exista y sea riguroso."""
        ruta_16 = os.path.join(DOCS_DIR, "analisis_papers", "16_tsne_y_umap.md")
        self.assertTrue(os.path.exists(ruta_16), f"Falta el archivo: {ruta_16}")

        with open(ruta_16, "r", encoding="utf-8") as f:
            contenido = f.read()

        # Debe tener más de 20 KB de análisis técnico exhaustivo
        self.assertGreater(len(contenido), 20000)

        # Autores y papers seminales
        self.assertIn("van der Maaten", contenido)
        self.assertIn("Hinton", contenido)
        self.assertIn("McInnes", contenido)
        self.assertIn("Healy", contenido)
        self.assertIn("Melville", contenido)

        # Teoremas y conceptos matemáticos clave
        conceptos_clave = [
            "Perplejidad",
            "Hacinamiento",
            "Cauchy",
            "Kullback-Leibler",
            "Entropía Cruzada Difusa",
            "Riemann",
            "Barnes-Hut",
            "Early Exaggeration",
        ]
        for c in conceptos_clave:
            self.assertIn(c.lower(), contenido.lower(), f"Falta concepto '{c}' en la monografía 16 de papers")

        # Código de referencia en Python
        self.assertIn("tSNE_Puro", contenido)
        self.assertIn("UMAP_MinimoPuro", contenido)
        self.assertIn("_calcular_probabilidades_p", contenido)
        self.assertIn("_construir_grafo_difuso", contenido)


    def test_monografia_17_analisis_papers(self):
        """Verifica que el análisis de papers de la monografía 17 (MLP y Backprop) exista y sea riguroso."""
        ruta_17 = os.path.join(DOCS_DIR, "analisis_papers", "17_mlp_y_backpropagation.md")
        self.assertTrue(os.path.exists(ruta_17), f"Falta el archivo: {ruta_17}")

        with open(ruta_17, "r", encoding="utf-8") as f:
            contenido = f.read()

        # Debe tener más de 20 KB de análisis técnico exhaustivo
        self.assertGreater(len(contenido), 20000)

        # Autores y papers seminales
        self.assertIn("Rumelhart", contenido)
        self.assertIn("Hinton", contenido)
        self.assertIn("Williams", contenido)
        self.assertIn("Cybenko", contenido)
        self.assertIn("Hornik", contenido)
        self.assertIn("Minsky", contenido)
        self.assertIn("Loshchilov", contenido)

        # Teoremas y conceptos matemáticos clave
        conceptos_clave = [
            "Aproximación Universal",
            "Backpropagation",
            "XOR",
            "Cross-Entropy",
            "Softmax",
            "AdamW",
            "Dropout",
            "He Normal",
        ]
        for c in conceptos_clave:
            self.assertIn(c.lower(), contenido.lower(), f"Falta concepto '{c}' en la monografía 17 de papers")

        # Código de referencia en Python
        self.assertIn("MLP_Puro", contenido)
        self.assertIn("step_adamw", contenido)
        self.assertIn("forward", contenido)
        self.assertIn("backward", contenido)


if __name__ == "__main__":
    unittest.main()


