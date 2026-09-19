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


if __name__ == "__main__":
    unittest.main()


