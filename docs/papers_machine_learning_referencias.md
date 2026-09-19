# Compendio de Papers Seminales de Machine Learning y Descomposición Modular

Este documento recopila las referencias científicas fundamentales de los algoritmos de Machine Learning y Deep Learning, especificando sus autores seminales, año de publicación, problemas que resuelven, formulación matemática esencial y su descomposición modular en bloques de procesamiento para el razonamiento automático de modelos de inteligencia artificial y su representación gráfica en diagramas de flujo.

---

## Índice General de Familias Algorítmicas

1. [Modelos Lineales y Regularizados (OLS, Ridge, Lasso, ElasticNet, Logistic Regression)](#1-modelos-lineales-y-regularizados)
2. [Máquinas de Vectores de Soporte (SVM, SVR, Kernel Trick)](#2-máquinas-de-vectores-de-soporte-svm-y-svr)
3. [Árboles de Decisión y Ensambles (CART, Random Forest, AdaBoost, GBM, XGBoost, LightGBM, CatBoost)](#3-árboles-de-decisión-y-ensambles)
4. [Métodos Basados en Instancias (k-Nearest Neighbors)](#4-métodos-basados-en-instancias-k-nn)
5. [Modelos Probabilísticos y Bayesianos (Naive Bayes, Procesos Gaussianos)](#5-modelos-probabilísticos-y-bayesianos)
6. [Agrupamiento y Aprendizaje No Supervisado (k-Means, DBSCAN, GMM / EM)](#6-agrupamiento-y-aprendizaje-no-supervisado)
7. [Reducción de Dimensionalidad y Variedades (PCA, Kernel PCA, t-SNE, UMAP)](#7-reducción-de-dimensionalidad-y-variedades)
8. [Deep Learning Clásico y Redes Neuronales (MLP, Backpropagation, CNN, ResNet, LSTM, GRU)](#8-deep-learning-clásico-y-redes-neuronales)
9. [Transformers, Autoatención y Modelos Fundacionales (Transformer, BERT, ViT)](#9-transformers-autoatención-y-modelos-fundacionales)
10. [Modelos Generativos y Difusión (VAE, GAN, DDPM)](#10-modelos-generativos-y-difusión)

---

## 1. Modelos Lineales y Regularizados

### 1.1. Mínimos Cuadrados Ordinarios (Ordinary Least Squares - OLS)
- **Autores & Año**: Adrien-Marie Legendre (1805, *Nouvelles méthodes pour la détermination des orbites des comètes*) y Carl Friedrich Gauss (1809, *Theoria Motus Corporum Coelestium*).
- **Problema que resuelve**: Ajuste lineal óptimo insesgado cuando los residuos son homocedásticos y no correlacionados (Teorema de Gauss-Markov).
- **Formulación Matemática**:
  $$\min_{w} \|Xw - y\|_2^2 \implies w^* = (X^T X)^{-1} X^T y$$
- **Bloques Modulares**:
  1. `[Matriz de Diseño X]`: Dimensión $(N, D)$ con vector de unos para el término de sesgo $b$.
  2. `[Proyección Ortogonal]`: Transformación lineal $X^T X$ y cálculo de la pseudoinversa.
  3. `[Cálculo de Coeficientes]`: $w^* \in \mathbb{R}^D$.
  4. `[Inferencia]`: $\hat{y} = X w^*$.

### 1.2. Regresión Ridge (Tikhonov Regularization / $L_2$)
- **Autores & Año**: Arthur E. Hoerl y Robert W. Kennard (1970). *Ridge Regression: Biased Estimation for Nonorthogonal Problems*. *Technometrics*, 12(1), 55-67.
- **Problema que resuelve**: Multicolinealidad en $X$ y matrices mal condicionadas donde $X^T X$ está cercana a la singularidad, estabilizando la varianza del estimador.
- **Formulación Matemática**:
  $$\min_{w} \left( \|Xw - y\|_2^2 + \lambda \|w\|_2^2 \right) \implies w^* = (X^T X + \lambda I)^{-1} X^T y$$
- **Bloques Modulares**:
  1. `[Entrada de Features]`: Estandarización centrada en media 0 y varianza 1.
  2. `[Penalización Cuadrática L2]`: Adición de $\lambda I$ en la diagonal de la matriz de covarianza muestral.
  3. `[Inversión Regularizada]`: Descomposición de Cholesky o SVD para resolver $(X^TX + \lambda I)^{-1}$.
  4. `[Shrinkage de Pesos]`: Coeficientes decrecen suavemente hacia cero sin llegar a anularse totalmente.

### 1.3. Lasso (Least Absolute Shrinkage and Selection Operator / $L_1$)
- **Autores & Año**: Robert Tibshirani (1996). *Regression Shrinkage and Selection via the Lasso*. *Journal of the Royal Statistical Society: Series B (Methodological)*, 58(1), 267-288.
- **Problema que resuelve**: Selección automática de variables (sparsity) eliminando características irrelevantes en espacios de alta dimensionalidad.
- **Formulación Matemática**:
  $$\min_{w} \left( \frac{1}{2N} \|Xw - y\|_2^2 + \alpha \|w\|_1 \right)$$
- **Bloques Modulares**:
  1. `[Espacio de Búsqueda Poliédrico]`: Romboide de restricción $\|w\|_1 \le t$.
  2. `[Descenso por Coordenadas (Coordinate Descent)]`: Actualización iterativa coordenada a coordenada mediante el operador de umbralización suave (Soft-Thresholding):
     $$S(z, \gamma) = \text{sign}(z)(|z| - \gamma)_+$$
  3. `[Selector de Características]`: Coeficientes no informativos colapsan exactamente a 0.
  4. `[Modelo Ralo (Sparse)]`: Retorno de subconjunto activo de variables.

### 1.4. Elastic Net
- **Autores & Año**: Hui Zou y Trevor Hastie (2005). *Regularization and variable selection via the elastic net*. *Journal of the Royal Statistical Society: Series B*, 67(2), 301-320.
- **Problema que resuelve**: Supera las limitaciones de Lasso cuando $P > N$ o cuando existen grupos de variables altamente correlacionadas (agrupamiento y selección simultánea).
- **Formulación Matemática**:
  $$\min_{w} \left( \frac{1}{2N} \|Xw - y\|_2^2 + \alpha \rho \|w\|_1 + \frac{\alpha (1-\rho)}{2} \|w\|_2^2 \right)$$
- **Bloques Modulares**:
  1. `[Penalización Híbrida L1 + L2]`: Mezcla convexa parametrizada por $\alpha$ y $\rho$ (l1_ratio).
  2. `[Efecto Agrupamiento (Grouping Effect)]`: La curvatura estrictamente convexa de $L_2$ selecciona variables correlacionadas juntas, mientras que $L_1$ induce esparsidad.
  3. `[Optimizador Proximal]`: Descenso por coordenadas con paso proximal.

### 1.5. Regresión Logística
- **Autores & Año**: David Cox (1958). *The Regression Analysis of Binary Sequences*. *Journal of the Royal Statistical Society: Series B*, 20(2), 215-242.
- **Problema que resuelve**: Clasificación binaria o multiclase probabilística modelando el log-odds de la variable objetivo.
- **Formulación Matemática**:
  $$P(y=1|x) = \sigma(w^T x + b) = \frac{1}{1 + e^{-(w^T x + b)}}$$
  $$\mathcal{L}_{BCE}(w) = -\frac{1}{N} \sum_{i=1}^N \left[ y_i \log(\hat{y}_i) + (1 - y_i) \log(1 - \hat{y}_i) \right]$$
- **Bloques Modulares**:
  1. `[Combinación Lineal]`: $z = w^T x + b$.
  2. `[Función de Enlace Sigmoide / Softmax]`: Mapeo de $\mathbb{R} \to [0, 1]$.
  3. `[Pérdida de Entropía Cruzada Binaria / Log-Loss]`: Función convexa de error.
  4. `[Optimizador Newton-Raphson / L-BFGS]`: Actualización mediante gradiente y matriz Hessiana $H = X^T W X$.

---

## 2. Máquinas de Vectores de Soporte (SVM y SVR)

### 2.1. Support Vector Classifier & Truco del Kernel
- **Autores & Año**: Corinna Cortes y Vladimir Vapnik (1995). *Support-Vector Networks*. *Machine Learning*, 20(3), 273-297. Bernardo Boser, Isabelle Guyon y Vladimir Vapnik (1992). *A training algorithm for optimal margin classifiers*. *COLT '92*, 144-152.
- **Problema que resuelve**: Clasificación con maximización del margen geométrico y separación no lineal en espacios de Hilbert de dimensión infinita.
- **Formulación Matemática**:
  $$\min_{w, b, \xi} \left( \frac{1}{2} \|w\|^2 + C \sum_{i=1}^N \xi_i \right) \quad \text{s.t.} \quad y_i(w^T \phi(x_i) + b) \ge 1 - \xi_i, \quad \xi_i \ge 0$$
  Formulación Dual de Lagrange:
  $$\max_{\alpha} \sum_{i=1}^N \alpha_i - \frac{1}{2} \sum_{i,j} \alpha_i \alpha_j y_i y_j K(x_i, x_j) \quad \text{s.t.} \quad 0 \le \alpha_i \le C, \quad \sum \alpha_i y_i = 0$$
- **Bloques Modulares**:
  1. `[Kernel Gram Matrix K(x, z)]`: Lineal, RBF/Gaussiano $e^{-\gamma \|x-z\|^2}$, o Polinómico $(x^T z + c)^d$.
  2. `[Optimizador Cuadrático Dual (SMO - Sequential Minimal Optimization)]`: Optimización de pares de multiplicadores $\alpha_i, \alpha_j$.
  3. `[Filtro de Vectores de Soporte]`: Identificación de muestras críticas con $\alpha_i > 0$.
  4. `[Decisión por Hiperplano Óptimo]`: $\hat{y} = \text{sign}\left( \sum_{i \in SV} \alpha_i y_i K(x_i, x) + b \right)$.

### 2.2. Support Vector Regression (SVR - Tubo $\varepsilon$-insensible)
- **Autores & Año**: Harris Drucker, Christopher Burges, Linda Kaufman, Alex Smola y Vladimir Vapnik (1997). *Support Vector Regression Machines*. *Advances in Neural Information Processing Systems (NeurIPS 9)*.
- **Problema que resuelve**: Regresión robusta ante outliers ignorando errores dentro de una banda de tolerancia $\varepsilon$.
- **Formulación Matemática**:
  $$L_\varepsilon(y, f(x)) = \max(0, |y - f(x)| - \varepsilon)$$
- **Bloques Modulares**:
  1. `[Tubo Épsilon-Insensible]`: Banda de tolerancia simétrica $[-\varepsilon, +\varepsilon]$.
  2. `[Variables de Holgura Dobles]`: $\xi_i$ para sobrestimaciones y $\xi_i^*$ para subestimaciones.
  3. `[Vectores de Soporte de Frontera]`: Puntos situados estrictamente fuera del tubo.

---

## 3. Árboles de Decisión y Ensambles

### 3.1. CART (Classification and Regression Trees)
- **Autores & Año**: Leo Breiman, Jerome Friedman, Richard Olshen y Charles Stone (1984). *Classification and Regression Trees*. Wadsworth & Brooks/Cole.
- **Problema que resuelve**: Partición recursiva binaria no paramétrica del espacio de características con interpretabilidad total.
- **Formulación Matemática**:
  - Clasificación (Impureza de Gini): $I_G(t) = 1 - \sum_{k=1}^K p_k^2$
  - Regresión (Varianza / MSE): $I_V(t) = \frac{1}{N_t} \sum_{i \in t} (y_i - \bar{y}_t)^2$
  - Criterio de Ganancia de División:
    $$\Delta I(s, t) = I(t) - \frac{N_L}{N_t} I(t_L) - \frac{N_R}{N_t} I(t_R)$$
- **Bloques Modulares**:
  1. `[Evaluador de Umbrales Óptimos]`: Búsqueda exhaustiva del feature $j$ y umbral $\theta$.
  2. `[Partición Binaria Recursiva]`: Bifurcación en nodos hijo izquierdo $x_j \le \theta$ y derecho $x_j > \theta$.
  3. `[Criterio de Parada]`: Profundidad máxima, mínimo de muestras por hoja o ganancia mínima.
  4. `[Poda de Complejidad de Coste (Cost-Complexity Pruning)]`: $R_\alpha(T) = R(T) + \alpha |T|$.

### 3.2. Random Forest (Bagging & Subespacios Aleatorios)
- **Autores & Año**: Leo Breiman (2001). *Random Forests*. *Machine Learning*, 45(1), 5-32. Tin Kam Ho (1995). *Random Decision Forests*. *ICDAR*.
- **Problema que resuelve**: Reducción drástica de la varianza (overfitting) de árboles individuales sin incrementar el sesgo, mediante descorrelación de estimadores.
- **Formulación Matemática**:
  $$\text{Var}(\bar{T}) = \rho \sigma^2 + \frac{1 - \rho}{B} \sigma^2$$
  Al reducir la correlación entre árboles $\rho$ mediante muestreo aleatorio de variables ($m = \sqrt{P}$), la varianza tiende a cero con $B \to \infty$.
- **Bloques Modulares**:
  1. `[Bootstrap Sampling]`: Muestreo con reemplazo de $N$ observaciones para cada uno de los $B$ árboles.
  2. `[Feature Subsampling]`: En cada división de nodo, selección aleatoria de $m \approx \sqrt{P}$ variables.
  3. `[Entrenamiento Paralelo Desacoplado]`: Construcción completa de $B$ árboles profundos no podados.
  4. `[Agregación por Ensamble]`: Votación mayoritaria (clasificación) o promedio aritmético (regresión).
  5. `[Estimación Out-Of-Bag (OOB)]`: Validación cruzada implícita sin conjunto de validación externo.

### 3.3. AdaBoost (Adaptive Boosting)
- **Autores & Año**: Yoav Freund y Robert E. Schapire (1997). *A Decision-Theoretic Generalization of On-Line Learning and an Application to Boosting*. *Journal of Computer and System Sciences*, 55(1), 119-139.
- **Problema que resuelve**: Conversión de estimadores débiles (weak learners, como decision stumps de 1 split) en un clasificador fuerte con garantías de convergencia en error de entrenamiento.
- **Formulación Matemática**:
  $$\alpha_m = \frac{1}{2} \ln\left( \frac{1 - \epsilon_m}{\epsilon_m} \right), \quad w_i^{(m+1)} = w_i^{(m)} \exp\left( -\alpha_m y_i h_m(x_i) \right)$$
- **Bloques Modulares**:
  1. `[Distribución de Pesos Muestrales]`: Inicialización uniforme $w_i = 1/N$.
  2. `[Entrenador de Estimador Débil]`: Ajuste de $h_m(x)$ sobre los datos ponderados.
  3. `[Cálculo de Importancia del Árbol α_m]`: Asignación de confianza según el ratio de aciertos.
  4. `[Re-ponderación Adaptativa]`: Aumento exponencial del peso de muestras falladas.
  5. `[Combinación Lineal Ponderada]`: $H(x) = \text{sign}\left( \sum_{m=1}^M \alpha_m h_m(x) \right)$.

### 3.4. Gradient Boosting Machine (GBM)
- **Autores & Año**: Jerome H. Friedman (2001). *Greedy Function Approximation: A Gradient Boosting Machine*. *The Annals of Statistics*, 29(5), 1189-1232.
- **Problema que resuelve**: Generalización del boosting a cualquier función de pérdida diferenciable mediante descenso de gradiente en el espacio de funciones.
- **Formulación Matemática**:
  $$r_{im} = -\left[ \frac{\partial L(y_i, F(x_i))}{\partial F(x_i)} \right]_{F(x) = F_{m-1}(x)}$$
  $$F_m(x) = F_{m-1}(x) + \eta \sum_{j=1}^{J_m} \gamma_{jm} \mathbb{I}(x \in R_{jm})$$
- **Bloques Modulares**:
  1. `[Inicialización F0(x)]`: Predicción constante que minimiza la pérdida global (ej. log-odds base o media).
  2. `[Cálculo de Pseudo-Residuos (Gradiente Negativo)]`: Diferencia entre valor real y predicción actual.
  3. `[Ajuste de Árbol a Residuos]`: Árbol de regresión $h_m(x)$ que modela la dirección de máximo descenso.
  4. `[Búsqueda de Paso Óptimo (Line Search)]`: Estimación del peso de hoja $\gamma_{jm}$.
  5. `[Actualización con Learning Rate (Shrinkage η)]`: $F_m = F_{m-1} + \eta \cdot \text{Árbol}_m$.

### 3.5. XGBoost (eXtreme Gradient Boosting)
- **Autores & Año**: Tianqi Chen y Carlos Guestrin (2016). *XGBoost: A Scalable Tree Boosting System*. *Proceedings of the 22nd ACM SIGKDD International Conference on Knowledge Discovery and Data Mining (KDD '16)*, 785-794. arXiv:1603.02754.
- **Problema que resuelve**: Eficiencia masiva, escalabilidad a billones de instancias, aproximación de Taylor de segundo orden y control riguroso de regularización en las hojas.
- **Formulación Matemática**:
  $$\mathcal{L}^{(t)} \approx \sum_{i=1}^n \left[ g_i f_t(x_i) + \frac{1}{2} h_i f_t^2(x_i) \right] + \gamma T + \frac{1}{2} \lambda \sum_{j=1}^T w_j^2$$
  donde $g_i = \partial_{\hat{y}^{(t-1)}} l(y_i, \hat{y}^{(t-1)})$ y $h_i = \partial^2_{\hat{y}^{(t-1)}} l(y_i, \hat{y}^{(t-1)})$.
  Puntuación de Calidad de División (Split Score):
  $$\mathcal{L}_{\text{split}} = \frac{1}{2} \left[ \frac{G_L^2}{H_L + \lambda} + \frac{G_R^2}{H_R + \lambda} - \frac{(G_L + G_R)^2}{H_L + H_R + \lambda} \right] - \gamma$$
- **Bloques Modulares**:
  1. `[Generador de Gradientes y Hessianos]`: Extracción de $g_i$ (1ª derivada) y $h_i$ (2ª derivada).
  2. `[Weighted Quantile Sketch]`: Algoritmo distribuido para generar candidatos de división en datos con pesos heterogéneos.
  3. `[Sparsity-Aware Split Finding]`: Asignación automática de ruta óptima para valores nulos/faltantes.
  4. `[Poda por Ganancia Mínima γ y Regularización L2 λ]`: Si $\mathcal{L}_{\text{split}} < 0$, la rama se poda.
  5. `[Optimización Hardware / Bloques en Memoria]`: Estructura en columnas preordenadas y acceso por buffer caché.

### 3.6. LightGBM (GOSS y EFB)
- **Autores & Año**: Guolin Ke, Qi Meng, Thomas Finley, Taifeng Wang, Wei Chen, Weidong Ma, Qiwei Ye y Tie-Yan Liu (2017). *LightGBM: A Highly Efficient Gradient Boosting Decision Tree*. *Advances in Neural Information Processing Systems (NeurIPS 30)*, 3146-3154.
- **Problema que resuelve**: Superar el cuello de botella del escaneo continuo de todas las variables e instancias para acelerar el entrenamiento en más de 20x.
- **Formulación Matemática**:
  - GOSS (Gradient-based One-Side Sampling): Mantiene las $a \times 100\%$ instancias con mayores gradientes y muestrea aleatoriamente una fracción $b$ de las instancias con gradientes pequeños, escalando su peso por $\frac{1 - a}{b}$.
  - EFB (Exclusive Feature Bundling): Algoritmo de coloración de grafos que fusiona variables mutuamente exclusivas en una única variable densa.
- **Bloques Modulares**:
  1. `[Filtro GOSS]`: Priorización de instancias con alto error de predicción.
  2. `[Agrupador EFB]`: Reducción del número de columnas sin pérdida informativa.
  3. `[Histogram-based Splitter]`: Discretización de variables continuas en $K=256$ bins discretos.
  4. `[Crecimiento Leaf-wise (Mejor Hoja Primero)]`: Expansión asimétrica del nodo con mayor pérdida residual en lugar de nivel por nivel (Depth-wise).

### 3.7. CatBoost (Ordered Boosting)
- **Autores & Año**: Liudmila Prokhorenkova, Gleb Gusev, Aleksandr Vorobev, Anna Veronika Dorogush y Andrey Gulin (2018). *CatBoost: unbiased boosting with categorical features*. *Advances in Neural Information Processing Systems (NeurIPS 31)*, 6638-6648. arXiv:1706.09516.
- **Problema que resuelve**: Elimina el *prediction shift* (fuga de etiquetas / target leakage) intrínseco en los algoritmos tradicionales de GBDT al calcular target encoding.
- **Formulación Matemática**:
  $$\hat{x}_k^i = \frac{\sum_{j=1}^{p-1} [x_{\sigma_j, k} = x_{\sigma_p, k}] y_{\sigma_j} + a \cdot P}{\sum_{j=1}^{p-1} [x_{\sigma_j, k} = x_{\sigma_p, k}] + a}$$
- **Bloques Modulares**:
  1. `[Permutaciones Aleatorias Múltiples σ]`: Simulación de series temporales artificiales para evitar que una instancia filtre su propia etiqueta.
  2. `[Ordered Target Statistics (TS)]`: Estimación de variables categóricas calculada únicamente con observaciones previas en la permutación.
  3. `[Árboles Oblivious (Simétricos)]`: Árboles balanceados donde cada nivel comparte exactamente el mismo criterio de división (máxima velocidad de evaluación en GPU).
  4. `[Ordered Boosting]`: Actualización de gradientes no sesgados.

---

## 4. Métodos Basados en Instancias (k-NN)

### 4.1. k-Nearest Neighbors (k-NN)
- **Autores & Año**: Thomas Cover y Peter Hart (1967). *Nearest Neighbor Pattern Classification*. *IEEE Transactions on Information Theory*, 13(1), 21-27. Evelyn Fix y Joseph Hodges (1951, USAF School of Aviation Medicine).
- **Problema que resuelve**: Clasificación y regresión no paramétrica perezosa (lazy learning) basada en geometría local en el espacio métrico.
- **Formulación Matemática**:
  $$d(x, z) = \left( \sum_{j=1}^D |x_j - z_j|^p \right)^{1/p} \quad \text{(Métrica de Minkowski)}$$
  $$\hat{y}(x) = \text{argmax}_{c} \sum_{i \in \mathcal{N}_k(x)} w_i \mathbb{I}(y_i = c), \quad w_i = \frac{1}{d(x, x_i) + \epsilon}$$
- **Bloques Modulares**:
  1. `[Estandarización de Espacio Métrico]`: Escalado indispensable para evitar que una variable domine las distancias.
  2. `[Estructura de Indexación Espacial]`: Búsqueda mediante KD-Tree o Ball-Tree para reducir la complejidad de $\mathcal{O}(ND)$ a $\mathcal{O}(D \log N)$.
  3. `[Extractor de k Vecinos Cercanos]`: Selección del vecindario top-$k$.
  4. `[Votación Ponderada por Distancia Inversa]`: Asignación final de clase o interpolación continua.

---

## 5. Modelos Probabilísticos y Bayesianos

### 5.1. Naive Bayes (Gaussiano, Multinomial, Bernoulli)
- **Autores & Año**: Richard O. Duda y Peter E. Hart (1973). *Pattern Classification and Scene Analysis*. John Wiley & Sons.
- **Problema que resuelve**: Clasificación probabilística ultrarrápida asumiendo independencia condicional de las características dada la clase.
- **Formulación Matemática**:
  $$P(y=c | x) \propto P(y=c) \prod_{j=1}^D P(x_j | y=c)$$
  - Gaussiano: $P(x_j | y=c) = \frac{1}{\sqrt{2\pi \sigma_{cj}^2}} \exp\left( -\frac{(x_j - \mu_{cj})^2}{2\sigma_{cj}^2} \right)$
  - Multinomial con Laplace Smoothing: $\hat{\theta}_{cj} = \frac{N_{cj} + \alpha}{N_c + \alpha D}$
- **Bloques Modulares**:
  1. `[Estimador de Priors P(y)]`: Frecuencia relativa de cada clase.
  2. `[Estimador de Verosimilitudes Condicionales P(x_j | y)]`: Cálculo de medias/varianzas o conteos por atributo.
  3. `[Acumulador Log-Probabilístico]`: $\log P(y) + \sum \log P(x_j | y)$ para evitar *underflow* numérico.
  4. `[Decisión MAP (Maximum A Posteriori)]`: $\hat{y} = \text{argmax}_c P(y=c|x)$.

### 5.2. Procesos Gaussianos (Gaussian Processes for Machine Learning)
- **Autores & Año**: Carl Edward Rasmussen y Christopher K. I. Williams (2006). *Gaussian Processes for Machine Learning*. MIT Press.
- **Problema que resuelve**: Inferencia no paramétrica con estimación exacta de incertidumbre epistémica (distribución completa a posteriori sobre funciones).
- **Formulación Matemática**:
  $$f(x) \sim \mathcal{GP}(m(x), k(x, x'))$$
  $$f_* | X, y, x_* \sim \mathcal{N}(\mu_*, \Sigma_*)$$
  $$\mu_* = K_*^T (K + \sigma_n^2 I)^{-1} y, \quad \Sigma_* = K_{**} - K_*^T (K + \sigma_n^2 I)^{-1} K_*$$
- **Bloques Modulares**:
  1. `[Definición de Matriz de Kernel de Covarianza K]`: RBF / Matérn / Periódico.
  2. `[Marginal Likelihood Maximization]`: Ajuste de hiperparámetros de kernel ($\sigma_f, l, \sigma_n$).
  3. `[Inversión de Matriz de Covarianza]`: Factorización de Cholesky de $(K + \sigma_n^2 I)$.
  4. `[Predicción Media y Banda de Confianza 95%]`: $\mu_* \pm 1.96 \sqrt{\Sigma_*}$.

---

## 6. Agrupamiento y Aprendizaje No Supervisado

### 6.1. k-Means (k-Medias)
- **Autores & Año**: J. MacQueen (1967). *Some Methods for classification and Analysis of Multivariate Observations*. *5th Berkeley Symp. Math. Statist. Prob.*, 1, 281-297. Arthur & Vassilvitskii (2007, *k-means++*).
- **Problema que resuelve**: Partición del espacio en $k$ grupos convexos minimizando la inercia intracluster (suma de cuadrados de distancias).
- **Formulación Matemática**:
  $$\min_{S} \sum_{j=1}^k \sum_{x \in S_j} \|x - \mu_j\|^2$$
- **Bloques Modulares**:
  1. `[Inicialización k-means++]`: Selección probabilística de centroides lejanos entre sí:
     $$P(x) = \frac{D(x)^2}{\sum_{x'} D(x')^2}$$
  2. `[Paso E (Asignación)]`: Cada punto se asigna al centroide $\mu_j$ más próximo en norma euclidiana.
  3. `[Paso M (Actualización)]`: Recálculo de centroides como la media baricéntrica $\mu_j = \frac{1}{|S_j|} \sum_{x \in S_j} x$.
  4. `[Convergencia]`: Parada cuando el desplazamiento $\|\mu_j^{(t)} - \mu_j^{(t-1)}\| < \epsilon$.

### 6.2. DBSCAN (Density-Based Spatial Clustering of Applications with Noise)
- **Autores & Año**: Martin Ester, Hans-Peter Kriegel, Jörg Sander y Xiaowei Xu (1996). *A Density-Based Algorithm for Discovering Clusters in Large Spatial Databases with Noise*. *KDD-96*, 226-231.
- **Problema que resuelve**: Detección de clústeres de forma arbitraria sin necesidad de prefijar $k$ y aislamiento robusto de valores atípicos (ruido).
- **Formulación Matemática**:
  - Vecindario-$\varepsilon$: $N_\varepsilon(p) = \{q \in D \mid \text{dist}(p, q) \le \varepsilon\}$
  - Punto Núcleo (Core Point): $|N_\varepsilon(p)| \ge \text{MinPts}$
  - Densidad alcanzable y conectividad por densidad.
- **Bloques Modulares**:
  1. `[Indexador Espacial Vecinal]`: Consulta de $N_\varepsilon(p)$ para cada punto.
  2. `[Clasificador de Tipos de Puntos]`: Núcleo (Core), Frontera (Border) o Ruido (Noise / Outlier).
  3. `[Expansor de Clúster por BFS/DFS]`: Propagación transitiva de puntos densamente conectados.
  4. `[Asignación de Etiquetas y Etiqueta -1 (Ruido)]`.

### 6.3. Gaussian Mixture Models (GMM) y Algoritmo EM
- **Autores & Año**: Arthur Dempster, Nan Laird y Donald Rubin (1977). *Maximum Likelihood from Incomplete Data via the EM Algorithm*. *Journal of the Royal Statistical Society: Series B*, 39(1), 1-38.
- **Problema que resuelve**: Agrupamiento probabilístico suave (soft clustering) modelando la densidad multivariante como superposición de $K$ distribuciones normales.
- **Formulación Matemática**:
  $$p(x) = \sum_{k=1}^K \pi_k \mathcal{N}(x \mid \mu_k, \Sigma_k)$$
  - Paso E (Expectation - Responsabilidades):
    $$\gamma_{ik} = \frac{\pi_k \mathcal{N}(x_i \mid \mu_k, \Sigma_k)}{\sum_{j=1}^K \pi_j \mathcal{N}(x_i \mid \mu_j, \Sigma_j)}$$
  - Paso M (Maximization):
    $$\mu_k^{new} = \frac{\sum_i \gamma_{ik} x_i}{\sum_i \gamma_{ik}}, \quad \Sigma_k^{new} = \frac{\sum_i \gamma_{ik} (x_i - \mu_k)(x_i - \mu_k)^T}{\sum_i \gamma_{ik}}$$
- **Bloques Modulares**:
  1. `[Inicialización de Parámetros Gaussianos]`: Medias, covarianzas y pesos de mezcla $\pi_k$.
  2. `[Cálculo de Matriz de Responsabilidad γ]`: Asignación blanda probabilística.
  3. `[Actualización de Momentos Ponderados]`: Recálculo de $\mu_k, \Sigma_k, \pi_k$.
  4. `[Evaluación de Log-Verosimilitud Marginal]`: Monitoreo de convergencia monotónica.

---

## 7. Reducción de Dimensionalidad y Variedades

### 7.1. Análisis de Componentes Principales (PCA)
- **Autores & Año**: Karl Pearson (1901, *Philosophical Magazine*) y Harold Hotelling (1933, *Journal of Educational Psychology*).
- **Problema que resuelve**: Reducción lineal de dimensionalidad preservando la máxima varianza geométrica y minimizando el error cuadrático de reconstrucción.
- **Formulación Matemática**:
  $$\text{Cov}(X) = \frac{1}{N-1} X^T X = V \Lambda V^T \implies Z = X V_k$$
  o mediante Descomposición en Valores Singulares (SVD):
  $$X = U S V^T \implies Z = U_k S_k$$
- **Bloques Modulares**:
  1. `[Centrado Obligatorio en Media Cero]`: $X_c = X - \bar{X}$.
  2. `[Descomposición Espectral o SVD]`: Autovalores $\lambda_i$ ordenados en sentido decreciente.
  3. `[Cálculo de Varianza Explicada Acumulada]`: Ratio $\frac{\sum_{i=1}^k \lambda_i}{\sum_{i=1}^D \lambda_i}$.
  4. `[Proyección Ortogonal en Subespacio Latente]`: $Z = X V_k \in \mathbb{R}^{N \times k}$.

### 7.2. t-SNE (t-Distributed Stochastic Neighbor Embedding)
- **Autores & Año**: Laurens van der Maaten y Geoffrey Hinton (2008). *Visualizing Data using t-SNE*. *Journal of Machine Learning Research*, 9, 2579-2605.
- **Problema que resuelve**: Visualización no lineal en 2D o 3D conservando fielmente las estructuras locales y vecindarios en espacios de alta dimensión.
- **Formulación Matemática**:
  Espacio de Entrada (Gaussiano):
  $$p_{j|i} = \frac{\exp(-\|x_i - x_j\|^2 / 2\sigma_i^2)}{\sum_{k \ne i} \exp(-\|x_i - x_k\|^2 / 2\sigma_i^2)}, \quad p_{ij} = \frac{p_{j|i} + p_{i|j}}{2N}$$
  Espacio de Salida (Distribución t de Student, 1 grado de libertad):
  $$q_{ij} = \frac{(1 + \|y_i - y_j\|^2)^{-1}}{\sum_{k \ne l} (1 + \|y_k - y_l\|^2)^{-1}}$$
  Función de Pérdida (Divergencia KL):
  $$\mathcal{L}_{KL}(P \parallel Q) = \sum_{i \ne j} p_{ij} \log \frac{p_{ij}}{q_{ij}}$$
- **Bloques Modulares**:
  1. `[Cálculo de Probabilidades Gaussianas de Afinidad P]`: Búsqueda binaria de varianzas $\sigma_i$ para satisfacer la *perplejidad* prefijada.
  2. `[Inicialización de Mapa Latente y]`: Pequeña distribución normal en $\mathbb{R}^2$.
  3. `[Distribución de Colas Pesadas (Student-t)]`: Elimina el efecto de hacinamiento (*crowding problem*).
  4. `[Descenso de Gradiente con Momento y Early Exaggeration]`: Dinámica de atracción local y repulsión global.

### 7.3. UMAP (Uniform Manifold Approximation and Projection)
- **Autores & Año**: Leland McInnes, John Healy y James Melville (2018). *UMAP: Uniform Manifold Approximation and Projection for Dimension Reduction*. arXiv:1802.03426.
- **Problema que resuelve**: Preservación simultánea de la estructura local y la topología global a alta velocidad de cómputo computacional.
- **Formulación Matemática**:
  Entropía Cruzada Borrosa:
  $$C(A, B) = \sum_{i \ne j} \left[ \mu_{ij} \log\left( \frac{\mu_{ij}}{\nu_{ij}} \right) + (1 - \mu_{ij}) \log\left( \frac{1 - \mu_{ij}}{1 - \nu_{ij}} \right) \right]$$
- **Bloques Modulares**:
  1. `[Aproximador de Variedad Local Riemanniana]`: Búsqueda de $k$-vecinos y estimación de métrica adaptativa local con radio $\rho_i$ y $\sigma_i$.
  2. `[Construcción de Complejo Simplicial Borroso]`: Grafo ponderado de afinidades difusas.
  3. `[Optimización Estocástica por Descenso de Gradiente (SGD)]`: Fuerza atractiva para aristas conectadas y fuerza repulsiva con muestreo negativo.

---

## 8. Deep Learning Clásico y Redes Neuronales

### 8.1. Perceptrón Multicapa (MLP) y Retropropagación del Error
- **Autores & Año**: David E. Rumelhart, Geoffrey E. Hinton y Ronald J. Williams (1986). *Learning representations by back-propagating errors*. *Nature*, 323, 533-536.
- **Problema que resuelve**: Aprendizaje de representaciones no lineales arbitrarias superando la limitación del XOR del perceptrón simple (Teorema de Aproximación Universal).
- **Formulación Matemática**:
  $$z^{[l]} = W^{[l]} a^{[l-1]} + b^{[l]}, \quad a^{[l]} = \phi(z^{[l]})$$
  $$\delta^{[l]} = \frac{\partial \mathcal{L}}{\partial z^{[l]}} = \left( (W^{[l+1]})^T \delta^{[l+1]} \right) \odot \phi'(z^{[l]})$$
- **Bloques Modulares**:
  1. `[Capa Densa (Linear Projection)]`: Multiplicación matricial $W \cdot x + b$.
  2. `[Activación No Lineal]`: ReLU $\max(0, z)$, LeakyReLU, GELU, o Sigmoid.
  3. `[Regularización por Dropout]`: Enmascaramiento estocástico de neuronas con probabilidad $p$.
  4. `[Forward Pass y Pérdida]`: Cálculo de error en la capa terminal.
  5. `[Backward Pass (Regla de la Cadena)]`: Propagación retrógrada de gradientes $\frac{\partial \mathcal{L}}{\partial W^{[l]}} = \delta^{[l]} (a^{[l-1]})^T$.

### 8.2. Redes Convolucionales (CNN) y Bloques Residuales (ResNet)
- **Autores & Año**: Yann LeCun et al. (1998, *LeNet-5*); Alex Krizhevsky, Ilya Sutskever, Geoffrey Hinton (2012, *AlexNet*, NeurIPS); Kaiming He, Xiangyu Zhang, Shaoqing Ren, Jian Sun (2016). *Deep Residual Learning for Image Recognition*. *CVPR*, 770-778. arXiv:1512.03385.
- **Problema que resuelve**: Extracción invariante a traslación espacial de patrones locales y eliminación del desvanecimiento del gradiente en redes ultra-profundas (+100 capas).
- **Formulación Matemática**:
  - Convolución 2D:
    $$(I * K)(i, j) = \sum_m \sum_n I(i-m, j-n) K(m, n)$$
  - Bloque Residual con Identidad:
    $$y = \mathcal{F}(x, \{W_i\}) + x$$
    $$\frac{\partial \mathcal{E}}{\partial x} = \frac{\partial \mathcal{E}}{\partial y} \left( \frac{\partial \mathcal{F}}{\partial x} + I \right)$$
- **Bloques Modulares**:
  1. `[Capa Convolucional 2D]`: Banco de filtros con kernel $3 \times 3$, stride y padding.
  2. `[Batch Normalization]`: Estabilización de covarianza interna mediante normalización de mini-batch $\hat{x} = \frac{x - \mu_B}{\sqrt{\sigma_B^2 + \epsilon}}$ con parámetros aprendibles $\gamma, \beta$.
  3. `[Función de Activación (ReLU)]`: No linealidad espacial.
  4. `[Submuestreo (MaxPool / Strided Conv)]`: Reducción dimensional preservando la activación dominante.
  5. `[Conexión de Salto Residual (Skip Connection)]`: Conexión de identidad que añade la entrada $x$ a la salida del bloque residual, permitiendo el flujo directo del gradiente $\frac{\partial \mathcal{E}}{\partial x} \ge \frac{\partial \mathcal{E}}{\partial y}$.

### 8.3. Redes Recurrentes con Compuertas (LSTM y GRU)
- **Autores & Año**: Sepp Hochreiter y Jürgen Schmidhuber (1997). *Long Short-Term Memory*. *Neural Computation*, 9(8), 1735-1780. Kyunghyun Cho et al. (2014, *GRU*, arXiv:1406.1078).
- **Problema que resuelve**: Modelado de dependencias temporales y secuenciales de largo alcance evitando el colapso exponencial del gradiente (*vanishing gradient*).
- **Formulación Matemática (LSTM)**:
  - Compuerta de Olvido: $f_t = \sigma(W_f [h_{t-1}, x_t] + b_f)$
  - Compuerta de Entrada: $i_t = \sigma(W_i [h_{t-1}, x_t] + b_i)$
  - Celda Candidata: $\tilde{C}_t = \tanh(W_c [h_{t-1}, x_t] + b_c)$
  - Estado de la Celda: $C_t = f_t \odot C_{t-1} + i_t \odot \tilde{C}_t$
  - Compuerta de Salida y Estado Oculto: $o_t = \sigma(W_o [h_{t-1}, x_t] + b_o), \quad h_t = o_t \odot \tanh(C_t)$
- **Bloques Modulares**:
  1. `[Autopista de Estado de Celda C_t]`: Conducción lineal aditiva que preserva el gradiente a través del tiempo sin decaimiento multiplicativo.
  2. `[Mecanismo de Compuertas Sigmoides (Gates)]`: Filtros analógicos entre 0 y 1.
  3. `[Estado Oculto Recurrente h_t]`: Memoria a corto plazo emitida a la siguiente capa temporal.

---

## 9. Transformers, Autoatención y Modelos Fundacionales

### 9.1. Arquitectura Transformer y Atención de Producto Escalar Escalado
- **Autores & Año**: Ashish Vaswani, Noam Shazeer, Niki Parmar, Jakob Uszkoreit, Llion Jones, Aidan N. Gomez, Łukasz Kaiser e Illia Polosukhin (2017). *Attention Is All You Need*. *Advances in Neural Information Processing Systems (NeurIPS 30)*, 5998-6008. arXiv:1706.03762.
- **Problema que resuelve**: Procesamiento de secuencias totalmente paralelizable con complejidad de trayecto $\mathcal{O}(1)$ entre cualquier par de tokens, eliminando la recurrencia secuencial.
- **Formulación Matemática**:
  $$\text{Attention}(Q, K, V) = \text{softmax}\left( \frac{Q K^T}{\sqrt{d_k}} \right) V$$
  $$\text{MultiHead}(Q, K, V) = \text{Concat}(\text{head}_1, \dots, \text{head}_h) W^O$$
  $$\text{head}_i = \text{Attention}(Q W_i^Q, K W_i^K, V W_i^V)$$
- **Bloques Modulares**:
  1. `[Input Token & Positional Encoding]`: Suma del vector embebido con codificación sinusoidal o RoPE (Rotary Position Embedding).
  2. `[Proyecciones Lineales Q, K, V]`: Transformaciones por matrices $W^Q, W^K, W^V \in \mathbb{R}^{d_{model} \times d_k}$.
  3. `[Scaled Dot-Product Attention]`: Matriz de atención $N \times N$ normalizada por $\sqrt{d_k}$ y softmax (con máscara causal opcional para decodificadores autorregresivos).
  4. `[Multi-Head Split & Concat]`: Múltiples cabezales de atención simultáneos que atienden a subespacios de representación distintos.
  5. `[Add & LayerNorm]`: Conexión residual + Layer Normalization sobre la dimensión del canal.
  6. `[Position-wise Feed-Forward Network (FFN)]`: Dos capas densas con activación intermedia (GELU / SwiGLU): $\text{FFN}(x) = \max(0, x W_1 + b_1) W_2 + b_2$.

### 9.2. Vision Transformer (ViT)
- **Autores & Año**: Alexey Dosovitskiy et al. (2020). *An Image is Worth 16x16 Words: Transformers for Image Recognition at Scale*. *ICLR 2021*. arXiv:2010.11929.
- **Problema que resuelve**: Aplicación directa del Transformer estándar a imágenes sin convoluciones, alcanzando rendimiento superior a gran escala con menor sesgo inductivo.
- **Formulación Matemática**:
  $$z_0 = [x_{\text{class}}; x_p^1 E; x_p^2 E; \dots; x_p^N E] + E_{\text{pos}}, \quad x_p \in \mathbb{R}^{P^2 \cdot C}, \quad E \in \mathbb{R}^{(P^2 \cdot C) \times D}$$
- **Bloques Modulares**:
  1. `[Patch Partition & Flatten]`: División de la imagen $H \times W \times C$ en $N = \frac{HW}{P^2}$ parches planos de tamaño $P \times P$.
  2. `[Linear Patch Projection]`: Transformación de cada parche plano a un vector de embedding continuo.
  3. `[Prepend Class Token [CLS]]`: Token aprendible inicial para clasificación agregada.
  4. `[Positional Embedding 1D 1D-Learnable]`: Preservación de la posición espacial de cada parche.
  5. `[Transformer Encoder Stack]`: Capas repetidas de Multi-Head Self-Attention y MLP.
  6. `[MLP Head Clasificador]`: Capa densa sobre el estado final del token `[CLS]`.

---

## 10. Modelos Generativos y Difusión

### 10.1. Variational Autoencoders (VAE)
- **Autores & Año**: Diederik P. Kingma y Max Welling (2013). *Auto-Encoding Variational Bayes*. *ICLR 2014*. arXiv:1312.6114.
- **Problema que resuelve**: Inferencia variacional tractable y generación de datos continuos mediante regularización del espacio latente con un prior estándar.
- **Formulación Matemática (ELBO - Evidence Lower Bound)**:
  $$\mathcal{L}_{ELBO}(\theta, \phi; x) = \mathbb{E}_{q_\phi(z|x)}[\log p_\theta(x|z)] - D_{KL}(q_\phi(z|x) \parallel p(z))$$
  Truco de Reparametrización:
  $$z = \mu(x) + \sigma(x) \odot \epsilon, \quad \epsilon \sim \mathcal{N}(0, I)$$
- **Bloques Modulares**:
  1. `[Codificador Probabilístico q_ϕ(z|x)]`: Red que predice el vector de medias $\mu(x)$ y log-varianzas $\log \sigma^2(x)$.
  2. `[Bloque de Reparametrización]`: Inyección de ruido estocástico exógeno $\epsilon \sim \mathcal{N}(0, I)$ para permitir que el gradiente fluya por $\mu$ y $\sigma$.
  3. `[Pérdida de Divergencia KL]`: Regularizador analítico que fuerza al espacio latente a comportarse como una gaussiana esférica estándar $\mathcal{N}(0, I)$.
  4. `[Decodificador Generativo p_θ(x|z)]`: Reconstrucción de la muestra original a partir del vector latente $z$.

### 10.2. Redes Generativas Antagónicas (GAN)
- **Autores & Año**: Ian J. Goodfellow et al. (2014). *Generative Adversarial Nets*. *Advances in Neural Information Processing Systems (NeurIPS 27)*, 2672-2680.
- **Problema que resuelve**: Generación de muestras de alta fidelidad sin requerir modelos probabilísticos explícitos, mediante un juego minimax de teoría de juegos entre dos redes.
- **Formulación Matemática**:
  $$\min_G \max_D V(D, G) = \mathbb{E}_{x \sim p_{\text{data}}(x)}[\log D(x)] + \mathbb{E}_{z \sim p_z(z)}[\log(1 - D(G(z)))]$$
- **Bloques Modulares**:
  1. `[Prior de Ruido Latente z ~ N(0, I)]`: Vector estocástico inicial.
  2. `[Generador G(z)]`: Red que mapea ruido a muestras sintéticas candidatas.
  3. `[Discriminador D(x)]`: Clasificador binario que distingue muestras reales de muestras artificiales producidas por $G$.
  4. `[Bucle de Entrenamiento Minimax Alternado]`: Paso 1: Maximizar acierto de $D$; Paso 2: Minimizar $\log(1 - D(G(z)))$ (o maximizar $\log D(G(z))$ para evitar desvanecimiento temprano del gradiente).

### 10.3. Modelos Probabilísticos de Difusión con Desruidificación (DDPM)
- **Autores & Año**: Jonathan Ho, Ajay Jain y Pieter Abbeel (2020). *Denoising Diffusion Probabilistic Models*. *Advances in Neural Information Processing Systems (NeurIPS 33)*, 6840-6851. arXiv:2006.11239. Sohl-Dickstein et al. (2015).
- **Problema que resuelve**: Generación de datos de máxima calidad superando a las GAN en diversidad y estabilidad de entrenamiento, modelando el proceso físico inverso de termodinámica estocástica.
- **Formulación Matemática**:
  - Proceso Forward (Adición de Ruido Gaussiano, programado por $\beta_t$):
    $$q(x_t \mid x_0) = \mathcal{N}(x_t \mid \sqrt{\bar{\alpha}_t} x_0, (1 - \bar{\alpha}_t) I), \quad \alpha_t = 1 - \beta_t, \quad \bar{\alpha}_t = \prod_{s=1}^t \alpha_s$$
    $$x_t = \sqrt{\bar{\alpha}_t} x_0 + \sqrt{1 - \bar{\alpha}_t} \epsilon, \quad \epsilon \sim \mathcal{N}(0, I)$$
  - Objetivo de Entrenamiento Simplificado:
    $$\mathcal{L}_{\text{simple}}(\theta) = \mathbb{E}_{t, x_0, \epsilon}\left[ \| \epsilon - \epsilon_\theta(x_t, t) \|^2 \right]$$
  - Proceso Reverse (Muestreo / Generación Iterativa):
    $$x_{t-1} = \frac{1}{\sqrt{\alpha_t}} \left( x_t - \frac{\beta_t}{\sqrt{1 - \bar{\alpha}_t}} \epsilon_\theta(x_t, t) \right) + \sigma_t z, \quad z \sim \mathcal{N}(0, I)$$
- **Bloques Modulares**:
  1. `[Noise Scheduler (Planificador de Ruido β_t)]`: Cronograma lineal o cosenoidal de adición de ruido en $T \approx 1000$ pasos.
  2. `[Forward Diffusion Jump]`: Cálculo directo de $x_t$ en tiempo constante $\mathcal{O}(1)$ usando $\sqrt{\bar{\alpha}_t}$.
  3. `[Red Neuronal Predictora de Ruido ε_θ (U-Net)]`: Arquitectura encoder-decoder con conexiones residuales laterales, bloques convolucionales y capas de autoatención cruzada condicionadas por el paso temporal $t$.
  4. `[Time-Step Embedding]`: Inyección del instante $t$ mediante embeddings sinusoidales en cada bloque de la U-Net.
  5. `[Bucle de Inferencia Desruidificadora (Reverse Sampling)]`: Reconstrucción paso a paso desde ruido puro $x_T \sim \mathcal{N}(0, I)$ hasta una muestra fotorrealista $x_0$.

---

## 11. Conclusión y Guía para Modelos de IA

Los modelos de razonamiento de Prig IDE pueden consultar esta base canónica para:
1. Descomponer cualquier pipeline de machine learning o deep learning en sus 4 etapas universales:
   - **Ingesta y Preprocesamiento** (Representación, codificación, normalización).
   - **Mecanismo de Transformación / Separación** (Capas, kernels, ramas de división, autoatención).
   - **Función de Pérdida y Algoritmo de Optimización** (Gradiente, aproximación de segundo orden, EM, Lagrange, backpropagation).
   - **Inferencia y Decisión** (Umbralización, votación ponderada, softmax, desruidificado).
2. Generar diagramas de flujo Mermaid formalmente correctos con esquemas de nodos y colores consistentes.
3. Explicar códigos de Kaggle identificando qué ecuación matemática y qué paper fundamenta cada línea de código.

