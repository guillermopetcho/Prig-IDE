# Monografía 16: t-SNE y UMAP — Reducción No Lineal de Variedades, Divergencia KL, Geometría Riemanniana y Entropía Cruzada Difusa

> **Directorio de Ubicación:** `docs/analisis_papers/16_tsne_y_umap.md`  
> **Ficha Técnica Modular Resumida:** [`docs/algoritmos_ml/16_tsne_y_umap.md`](../algoritmos_ml/16_tsne_y_umap.md)  
> **Estado del Documento:** Riguroso / Nivel Doctoral / Producción Académica  

---

## 1. Ficha Bibliográfica y Genealogía de Papers Seminales

1. **La Formulación Estocástica Original: SNE (NIPS, 2002):**
   - **Título:** *Stochastic Neighbor Embedding*
   - **Autores:** Geoffrey E. Hinton y Sam T. Roweis.
   - **Publicación:** *Advances in Neural Information Processing Systems (NIPS 2002)*, 15, pp. 833–840.
   - **Aporte Principal:** Introducción del paradigma de conversión de distancias euclidianas entre muestras en probabilidades condicionales de vecindad $p_{j|i}$ y $q_{j|i}$ mediante distribuciones gaussianas tanto en el espacio de alta como de baja dimensión, optimizadas minimizando la divergencia de Kullback-Leibler.

2. **El Paper Canónico de t-SNE y la Solución al Hacinamiento (JMLR, 2008):**
   - **Título:** *Visualizing Data using t-SNE*
   - **Autores:** Laurens van der Maaten y Geoffrey E. Hinton.
   - **Publicación:** *Journal of Machine Learning Research*, 9(Nov), pp. 2579–2605 (2008).
   - **Aporte Principal:** Simetrización de las probabilidades conjuntas $p_{ij}$ y sustitución crítica de la distribución normal latente por una **distribución $t$ de Student con 1 grado de libertad (distribución de Cauchy)**. Esta modificación resolvió analíticamente el *problema del hacinamiento* (*crowding problem*) y simplificó enormemente el gradiente analítico.

3. **Aceleración Algorítmica Espacial: Barnes-Hut t-SNE (JMLR, 2014):**
   - **Título:** *Accelerating t-SNE using Tree-Based Algorithms*
   - **Autor:** Laurens van der Maaten.
   - **Publicación:** *Journal of Machine Learning Research*, 15(1), pp. 3221–3245 (2014).
   - **Aporte Principal:** Reducción de la complejidad computacional de $\mathcal{O}(N^2)$ a $\mathcal{O}(N \log N)$ mediante árboles espaciales (Quadtrees en 2D, Octrees en 3D) aplicando la aproximación de campo lejano de Barnes-Hut para evaluar las fuerzas repulsivas entre grupos de partículas distantes.

4. **Aceleración por Transformada Rápida de Fourier: FIt-SNE (Nature Methods, 2019):**
   - **Título:** *Fast interpolation-based t-SNE for improved visualization of single-cell RNA-seq data*
   - **Autores:** George C. Linderman, Manas Rachh, Jeremy G. Hoskins, Stefan Steinerberger y Yuval Kluger.
   - **Publicación:** *Nature Methods*, 16(3), pp. 235–240 (2019).
   - **Aporte Principal:** Interpolación de potenciales sobre mallas regulares unidimensionales y bidimensionales con polinomios de Chebyshev y convolución acelerada por Fast Fourier Transform (FFT), reduciendo la complejidad a $\mathcal{O}(N)$ y habilitando t-SNE en conjuntos de datos con millones de observaciones (e.g. transcriptómica unicelular).

5. **El Manifiesto de UMAP: Geometría Riemanniana y Complejos Simpliciales Difusos (2018):**
   - **Título:** *UMAP: Uniform Manifold Approximation and Projection for Dimension Reduction*
   - **Autores:** Leland McInnes, John Healy y James Melville.
   - **Publicación:** *arXiv:1802.03426* (2018).
   - **Aporte Principal:** Fundamentación teórica rigurosa sobre geometría diferencial riemanniana y topología algebraica difusa. Definición de métricas locales normalizadas que garantizan conectividad estricta a distancia cero ($\rho_i$), construcción de grafos simpliciales difusos y optimización de **Entropía Cruzada Difusa** con muestreo negativo estocástico, preservando simultáneamente la estructura local y la macro-topología global.

6. **Construcción Eficiente del Grafo de Vecinos: NN-Descent (WWW, 2011):**
   - **Título:** *Efficient k-nearest neighbor graph construction for generic spaces*
   - **Autores:** Wei Dong, Moses Charikar y Kai Li (Princeton University).
   - **Publicación:** *Proceedings of the 20th international conference on World Wide Web*, pp. 577–586 (2011).
   - **Aporte Principal:** Algoritmo aproximado para la construcción del grafo $k$-NN en métricas arbitrarias con complejidad temporal empírica $\mathcal{O}(N^{1.14})$, basado en el principio heurístico de que *los vecinos de mis vecinos tienen alta probabilidad de ser también mis vecinos*. Motor computacional subyacente de UMAP.

---

## 2. Génesis Teórica: Ruptura con la Linealidad y el Problema del Hacinamiento

Los métodos lineales clásicos (PCA, Factor Analysis, Classical MDS) asumen que los datos observados $\mathcal{X} \subset \mathbb{R}^D$ residen sobre un hiperplano lineal o afín.  
Cuando los datos yacen sobre una **variedad no lineal intrínseca** de dimensión $d \ll D$ (como una cinta de Moebius, un toro o un rollo suizo *Swiss Roll*), la proyección ortogonal lineal colapsa regiones lejanas de la variedad sobre los mismos puntos del plano proyectado.

### 2.1. El Problema del Hacinamiento (*The Crowding Problem*)

Considérese una esfera $D$-dimensional centrada en el origen con radio $R$.  
Su volumen geométrico está dado por:
$$\text{Vol}_D(R) = \frac{\pi^{D/2}}{\Gamma\left(\frac{D}{2} + 1\right)} R^D$$
La fracción del volumen contenida en una corteza externa delgada de espesor $\epsilon R$ (donde $0 < \epsilon < 1$) es:
$$\frac{\text{Vol}_D(R) - \text{Vol}_D(R(1 - \epsilon))}{\text{Vol}_D(R)} = 1 - (1 - \epsilon)^D$$
Cuando $D \to \infty$, para cualquier $\epsilon > 0$:
$$\lim_{D \to \infty} \left[ 1 - (1 - \epsilon)^D \right] = 1$$

```
   Espacio de Entrada (Alta Dimensión D >> 2)           Espacio Latente (Baja Dimensión d = 2)
  ┌──────────────────────────────────────────────┐     ┌──────────────────────────────────────┐
  │ En ℝ^D, el volumen disponible crece como r^D.│     │ En ℝ², el área disponible crece solo │
  │ Pueden existir N puntos mutuamente           │     │ como r². ¡No hay espacio físico para │
  │ equidistantes alrededor de x_i sin interferir│     │ mantener N puntos equidistantes!     │
  │ entre sí.                                    │     │                                      │
  └──────────────────────┬───────────────────────┘     └──────────────────┬───────────────────┘
                         │                                                │
                         └──────────────► EFECTO MATEMÁTICO ──────────────┘
                                          Si se usa Gaussiana en ℝ²:
                                          Para modelar distancias moderadas,
                                          todos los puntos son aplastados
                                          hacia el centro en un disco amorfo.
```

**Consecuencia en Visualización Dimensional:**  
En un espacio de alta dimensión ($D = 100$), existen infinitamente más direcciones ortogonales para acomodar puntos vecinos moderadamente distantes que en el plano bidimensional ($d = 2$).  
Si intentamos preservar exactamente las probabilidades gaussianas en $\mathbb{R}^2$ (como hacía SNE original):
$$q_{j|i} \propto \exp(-\|y_i - y_j\|^2)$$
la masa de probabilidad requerida para representar distancias intermedias fuerza a los puntos a empujarse mutuamente hacia el centro del espacio latente, creando una **congestión masiva y amorfa** donde los distintos clústeres pierden su separación y colapsan en una masa indistinguible.

### 2.2. La Solución de van der Maaten y Hinton: Distribución $t$ de Student
Para contrarrestar la falta de volumen geométrico en $d = 2$, t-SNE sustituye la distribución gaussiana latente por una **distribución $t$ de Student con un único grado de libertad** (equivalente a una distribución de Cauchy):
$$q_{ij} \propto (1 + \|y_i - y_j\|^2)^{-1}$$
Para distancias grandes $d_{ij} = \|y_i - y_j\| \gg 1$:
- La densidad gaussiana decae exponencialmente: $\exp(-d_{ij}^2) \to 0$ con extrema rapidez.
- La densidad de Cauchy decae con una **ley de potencia cuadrática inversa**: $\frac{1}{d_{ij}^2}$.

**El Efecto Repulsor de las Colas Pesadas:**  
Dado que $q_{ij}$ decae mucho más lentamente que la exponencial a distancias moderadas, un par de puntos con una disimilitud pequeña o intermedia en alta dimensión ($p_{ij}$ moderado) puede situarse a una **distancia euclidiana mucho mayor** en el plano $y \in \mathbb{R}^2$ sin que $q_{ij}$ sea penalizado severamente. Esto crea una fuerza de repulsión natural que "abre" la variedad y revela agrupamientos aislados con espacios en blanco limpios.

---

## 3. Derivaciones Matemáticas Paso a Paso

### 3.1. t-SNE: De Afinidades Gaussianas al Gradiente de Divergencia KL

#### 1. Probabilidades Condicionales en Alta Dimensión
Para cada punto $x_i \in \mathbb{R}^D$, centramos una gaussiana isotrópica con varianza $\sigma_i^2$:
$$p_{j|i} = \frac{\exp\left(-\frac{\|x_i - x_j\|^2}{2\sigma_i^2}\right)}{\sum_{k \ne i} \exp\left(-\frac{\|x_i - x_k\|^2}{2\sigma_i^2}\right)}, \quad \text{con } p_{i|i} = 0$$

#### 2. Calibración de la Varianza Local Mediante Perplejidad
La dispersión local $\sigma_i$ se adapta automáticamente a la densidad alrededor de $x_i$ resolviendo:
$$\text{Perp}(P_i) = 2^{H(P_i)}$$
donde $H(P_i)$ es la **entropía de Shannon** de la distribución condicional $P_i = (p_{1|i}, \dots, p_{N|i})$:
$$H(P_i) = -\sum_{j \ne i} p_{j|i} \log_2 p_{j|i}$$
Dado que $H(P_i)$ es una función monótona estrictamente creciente respecto a $\sigma_i$, el valor exacto de $\sigma_i$ se determina mediante una **búsqueda binaria unidimensional** por bisección hasta que $|\log_2(\text{Perp}) - H(P_i)| < \epsilon$.

#### 3. Simetrización de Probabilidades Conjuntas
Para robustecer el modelo frente a puntos atípicos (*outliers*) aislados (para los cuales $\sum_j p_{i|j}$ sería casi nulo):
$$p_{ij} = \frac{p_{j|i} + p_{i|j}}{2N}, \quad \text{con } p_{ii} = 0, \quad \sum_{i,j} p_{ij} = 1$$

#### 4. Distribución Latente con Distribución de Cauchy
Sean $y_1, \dots, y_N \in \mathbb{R}^d$ las coordenadas latentes (típicamente $d = 2$).  
Definimos las afinidades no normalizadas $w_{ij}$:
$$w_{ij} = (1 + \|y_i - y_j\|^2)^{-1}, \quad \text{con } w_{ii} = 0$$
La probabilidad conjunta normalizada en el espacio de proyección es:
$$q_{ij} = \frac{w_{ij}}{\sum_{k} \sum_{l \ne k} w_{kl}} = \frac{(1 + \|y_i - y_j\|^2)^{-1}}{\sum_{k \ne l} (1 + \|y_k - y_l\|^2)^{-1}}$$

#### 5. Función de Pérdida: Divergencia de Kullback-Leibler
$$\mathcal{L}_{\text{KL}}(P \parallel Q) = \sum_{i \ne j} p_{ij} \ln \frac{p_{ij}}{q_{ij}} = \sum_{i \ne j} p_{ij} \ln p_{ij} - \sum_{i \ne j} p_{ij} \ln q_{ij}$$

#### 6. Derivación Rigurosa del Gradiente Analítico
Calculamos la derivada parcial respecto a la posición del punto $y_i$:
$$\frac{\partial \mathcal{L}_{\text{KL}}}{\partial y_i} = - \sum_{j \ne i} p_{ij} \frac{1}{q_{ij}} \frac{\partial q_{ij}}{\partial y_i} - \sum_{j \ne i} p_{ji} \frac{1}{q_{ji}} \frac{\partial q_{ji}}{\partial y_i} = - 2 \sum_{j \ne i} \frac{p_{ij}}{q_{ij}} \frac{\partial q_{ij}}{\partial y_i}$$
dado que $p_{ij} = p_{ji}$ y $q_{ij} = q_{ji}$.

Sea $Z = \sum_{k \ne l} w_{kl}$. Entonces $q_{ij} = \frac{w_{ij}}{Z}$.  
Aplicando la regla del cociente:
$$\frac{\partial q_{ij}}{\partial y_i} = \frac{\frac{\partial w_{ij}}{\partial y_i} Z - w_{ij} \frac{\partial Z}{\partial y_i}}{Z^2} = \frac{1}{Z} \frac{\partial w_{ij}}{\partial y_i} - \frac{w_{ij}}{Z^2} \frac{\partial Z}{\partial y_i}$$
Calculamos $\frac{\partial w_{ij}}{\partial y_i}$:
$$\frac{\partial w_{ij}}{\partial y_i} = - (1 + \|y_i - y_j\|^2)^{-2} \cdot 2(y_i - y_j) = - 2 w_{ij}^2 (y_i - y_j)$$
Calculamos $\frac{\partial Z}{\partial y_i}$:
$$\frac{\partial Z}{\partial y_i} = \frac{\partial}{\partial y_i} \left[ \sum_{k \ne l} w_{kl} \right] = 2 \sum_{j \ne i} \frac{\partial w_{ij}}{\partial y_i} = - 4 \sum_{j \ne i} w_{ij}^2 (y_i - y_j)$$
Sustituyendo estas derivadas en la expresión de $\frac{\partial q_{ij}}{\partial y_i}$:
$$\frac{\partial q_{ij}}{\partial y_i} = - \frac{2 w_{ij}^2 (y_i - y_j)}{Z} + \frac{w_{ij}}{Z} \left[ \frac{4 \sum_k w_{ik}^2 (y_i - y_k)}{Z} \right] = - 2 q_{ij} w_{ij} (y_i - y_j) + 4 q_{ij} \sum_k q_{ik} w_{ik} (y_i - y_k)$$
Multiplicando por $-\frac{2 p_{ij}}{q_{ij}}$ y sumando sobre todos los $j \ne i$:
$$\frac{\partial \mathcal{L}_{\text{KL}}}{\partial y_i} = 4 \sum_{j \ne i} p_{ij} w_{ij} (y_i - y_j) - 8 \left( \sum_{j \ne i} p_{ij} \right) \sum_k q_{ik} w_{ik} (y_i - y_k)$$
Dado que $\sum_{j \ne i} p_{ij} = p_i$ (y sumando sobre la distribución simétrica marginal $\sum_j p_{ij} = \frac{1}{N}$, mientras que en la formulación de van der Maaten & Hinton el factor $2$ de simetría se absorbe en el gradiente global):
$$\frac{\partial \mathcal{L}_{\text{KL}}}{\partial y_i} = 4 \sum_{j=1}^N (p_{ij} - q_{ij})(y_i - y_j)(1 + \|y_i - y_j\|^2)^{-1}$$

**Interpretación Física:**  
El gradiente modela un sistema de partículas interactuando mediante dos fuerzas opuestas:
1. **Fuerza Atractiva:** $+4 \sum_j p_{ij} w_{ij} (y_i - y_j)$. Actúa como un resorte entre puntos vecinos en alta dimensión ($p_{ij} > 0$).
2. **Fuerza Repulsiva:** $-4 \sum_j q_{ij} w_{ij} (y_i - y_j)$. Ejerce una repulsión electrostática entre todos los pares de partículas, evitando que colapsen en un punto singular.

---

### 3.2. UMAP: Geometría Riemanniana y Entropía Cruzada Difusa

#### 1. Postulados Teóricos de UMAP
1. Los datos yacen sobre una **variedad riemanniana** conexa $\mathcal{M}$.
2. La métrica riemanniana es **localmente constante** en el entorno de cada punto.
3. La variedad es **localmente conexa** en todo punto.

#### 2. La Métrica Localmente Adaptativa y el Radio $\rho_i$
Para satisfacer el postulado de conectividad local estricta, McInnes et al. definen la distancia al primer vecino más cercano:
$$\rho_i = \min \{ d(x_i, x_j) \mid j \ne i, d(x_i, x_j) > 0 \}$$
La probabilidad condicional difusa de pertenencia a la variedad es:
$$p_{j|i} = \exp\left( -\frac{\max(0, d(x_i, x_j) - \rho_i)}{\sigma_i} \right)$$
Nótese que para el vecino más cercano $x_{j^*}$ tal que $d(x_i, x_{j^*}) = \rho_i$:
$$p_{j^*|i} = \exp\left( -\frac{0}{\sigma_i} \right) = \exp(0) = 1$$
Esto garantiza que **todo punto tenga un grado de pertenencia difusa exactamente igual a 1 con su vecino más próximo**, erradicando el problema de puntos desconectados en regiones de densidad dispersa.

El parámetro de escala $\sigma_i$ se resuelve determinísticamente imponiendo:
$$\sum_{j=1}^k \exp\left( -\frac{\max(0, d(x_i, x_j) - \rho_i)}{\sigma_i} \right) = \log_2(k)$$
donde $k$ es el número de vecinos (`n_neighbors`).

#### 3. Simetrización Mediante Unión Difusa (T-Conorma Algebraica)
En lugar del promedio aritmético de t-SNE, UMAP aplica la unión de conjuntos difusos estándar:
$$p_{ij} = p_{j|i} + p_{i|j} - p_{j|i} p_{i|j}$$

#### 4. Modelado en Baja Dimensión Mediante Curvas Paramétricas
En el espacio latente $y \in \mathbb{R}^d$, la probabilidad de similitud es:
$$q_{ij} = \left( 1 + a \|y_i - y_j\|_2^{2b} \right)^{-1}$$
donde los hiperparámetros $a$ y $b$ se ajustan mediante mínimos cuadrados no lineales para aproximar la función de corte suave determinada por `min_dist`:
$$\psi(d) \approx \begin{cases} 1 & \text{si } d \le \text{min\_dist} \\ \exp(-(d - \text{min\_dist})) & \text{si } d > \text{min\_dist} \end{cases}$$
Para los valores estándar (`min_dist=0.1`), típicamente $a \approx 1.5769$ y $b \approx 0.8950$. Cuando $a=1, b=1$, se recupera la distribución de Cauchy de t-SNE.

#### 5. Función de Pérdida: Entropía Cruzada Difusa (*Fuzzy Cross-Entropy*)
A diferencia de t-SNE que utiliza la divergencia KL sobre distribuciones de probabilidad normalizadas ($P$ y $Q$), UMAP trata a $p_{ij}$ y $q_{ij}$ como **grados de pertenencia de conjuntos difusos independientes**:
$$\mathcal{L}_{\text{UMAP}} = \sum_{i \ne j} \left[ \underbrace{p_{ij} \ln \frac{p_{ij}}{q_{ij}}}_{\text{Atracción (Preserva Vecindad Local)}} + \underbrace{(1 - p_{ij}) \ln \frac{1 - p_{ij}}{1 - q_{ij}}}_{\text{Repulsión (Preserva Topología Global)}} \right]$$

#### 6. Por Qué UMAP Preserva la Topología Global y t-SNE No
Comparemos las derivadas respecto a pares lejanos donde $p_{ij} = 0$:
- **En t-SNE:**
  Si dos puntos están muy lejanos en alta dimensión, $p_{ij} = 0$.  
  El término en la divergencia KL es $p_{ij} \ln \frac{p_{ij}}{q_{ij}} = 0 \ln(0) = 0$.  
  Por lo tanto, **el gradiente atractivo es cero y la repulsión depende exclusivamente del denominador normalizador global $Z$**. t-SNE es completamente ciego a las distancias relativas entre macro-clústeres desconectados.
- **En UMAP:**
  Si dos puntos están muy lejanos ($p_{ij} = 0$), el segundo término de la entropía cruzada difusa se activa:
  $$(1 - 0) \ln \frac{1 - 0}{1 - q_{ij}} = - \ln (1 - q_{ij})$$
  Su gradiente respecto a $y_i$ es:
  $$\frac{\partial}{\partial y_i} [-\ln(1 - q_{ij})] = \frac{1}{1 - q_{ij}} \frac{\partial q_{ij}}{\partial y_i} \ne 0$$
  Este término ejerce una **fuerza repulsiva activa y explícita para cada par disimilar**, empujando a los macro-clústeres a posicionarse en el plano latente de acuerdo a sus verdaderas distancias geodésicas globales.

---

## 4. Arquitectura de Sistemas y Algoritmos de Aceleración

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 ALTA DIMENSIÓN X ∈ ℝ^(N×D)                                      │
└────────────────────────────────────────────────┬────────────────────────────────────────────────┘
                                                 │
                   ┌─────────────────────────────┴─────────────────────────────┐
                   ▼                                                           ▼
┌──────────────────────────────────────┐                   ┌──────────────────────────────────────┐
│       Pipeline t-SNE Canónico        │                   │        Pipeline UMAP Canónico        │
├──────────────────────────────────────┤                   ├──────────────────────────────────────┤
│ 1. Reducción previa con PCA (D -> 50)│                   │ 1. K-NN Graph vía NN-Descent         │
│ 2. Quadtree / Barnes-Hut (O(N log N))│                   │    Complejidad empírica O(N^1.14)    │
│    o FIt-SNE / FFT (O(N))            │                   │ 2. Inicialización Espectral:         │
│ 3. Inicialización PCA o Aleatoria    │                   │    Autovectores de Laplaciano L = D-W│
│ 4. Early Exaggeration (x12, 250 it)  │                   │ 3. Optimización SGD con Muestreo     │
│ 5. Descenso con Momento Nesterov     │                   │    Negativo (Negative Sampling)      │
└──────────────────────────────────────┘                   └──────────────────────────────────────┘
```

### 4.1. Aproximación Barnes-Hut en t-SNE
En lugar de calcular las $\mathcal{O}(N^2)$ interacciones repulsivas punto a punto:
1. Se construye un Quadtree (en 2D) subdividiendo recursivamente el espacio latente hasta que cada celda contenga a lo sumo un punto.
2. Para evaluar la repulsión ejercida sobre el punto $y_i$ por una celda de tamaño $r$ cuyo centro de masa está a distancia $D$, se evalúa el criterio de apertura angular:
   $$\frac{r}{D} < \theta, \quad \text{con } \theta \approx 0.5$$
3. Si la condición se cumple, la celda entera se trata como **un único super-punto con masa acumulada**, reduciendo el cómputo repulsivo a $\mathcal{O}(N \log N)$.

### 4.2. Muestreo Negativo Estocástico en UMAP
Calcular la suma de repulsión sobre todos los pares con $p_{ij} = 0$ requeriría $\mathcal{O}(N^2)$ operaciones por iteración.  
Inspirándose en Word2Vec (Mikolov et al., 2013), UMAP aplica **Negative Sampling**:
- Para cada arista positiva existente en el grafo $k$-NN ($p_{ij} > 0$), se optimiza la atracción hacia adelante.
- Se seleccionan aleatoriamente $M$ nodos negativos uniformes ($M \approx 5$) para optimizar la fuerza de repulsión:
  $$\mathcal{L}_{\text{muestreo}} = \ln q_{ij} + \sum_{m=1}^M \ln(1 - q_{i, j_m})$$
- Esto reduce el costo computacional de la fase de optimización a estrictamente $\mathcal{O}(N \cdot k \cdot M) \approx \mathcal{O}(N)$.

---

## 5. Tabla Comparativa Exhaustiva

| Parámetro / Característica | t-SNE (van der Maaten & Hinton) | UMAP (McInnes et al.) |
|---|---|---|
| **Base Teórica** | Probabilidad condicional e información (KL) | Geometría Riemanniana y Topología Algebraica |
| **Preservación Local** | Extraordinaria (clústeres densos bien aislados) | Extraordinaria (detalles microscópicos) |
| **Preservación Global** | Pobre (las distancias entre clústeres no tienen significado) | Moderada a Buena (preserva orden relativo macro) |
| **Complejidad Temporal** | $\mathcal{O}(N \log N)$ (Barnes-Hut) / $\mathcal{O}(N)$ (FIt-SNE) | $\mathcal{O}(N^{1.14})$ (NN-Descent + SGD) |
| **Inicialización Canónica** | Aleatoria $\mathcal{N}(0, 10^{-4})$ o PCA | Laplaciano de Grafo / *Spectral Embedding* |
| **Proyección de Nuevos Puntos** | **No soportada nativamente** (optimización no paramétrica) | **Soportada** (`transform` proyecta sobre grafo existente) |
| **Sensibilidad a Hiperparámetros** | Alta (`perplexity`, `early_exaggeration`, `lr`) | Moderada (`n_neighbors`, `min_dist`) |
| **Uso en Dimensiones $d > 3$** | Ineficiente / colapsa numéricamente | Funciona fluidamente para $d = 10, 20$ como pre-proceso |

---

## 6. Implementación Pura en Python y NumPy (Sin scikit-learn ni librerías de ML)

A continuación se desarrolla una implementación completa, vectorizada y matemáticamente fiel de **t-SNE Puro** (con búsqueda binaria de $\sigma_i$ por perplejidad, simetrización $P$, distribución $t$ de Cauchy y optimizador con momento) y **UMAP Simplificado** (con radios locales $\rho_i$, unión algebraica y descenso de entropía cruzada difusa).

```python
import numpy as np


class tSNE_Puro:
    """
    Implementación rigurosa de t-Distributed Stochastic Neighbor Embedding (t-SNE).
    Resuelve la búsqueda binaria de sigma_i para alcanzar la perplejidad objetivo,
    utiliza distribución de Cauchy en el espacio latente y minimiza la divergencia
    de Kullback-Leibler con Early Exaggeration y Momento de Nesterov.
    """
    def __init__(self, n_components=2, perplexity=30.0, n_iter=300, 
                 lr=200.0, early_exaggeration=4.0, random_state=42):
        self.n_components = n_components
        self.perplexity = perplexity
        self.n_iter = n_iter
        self.lr = lr
        self.early_exaggeration = early_exaggeration
        self.random_state = random_state
        self.embedding_ = None
        self.kl_divergence_ = None

    def _calcular_probabilidades_p(self, X, tol=1e-5, max_iter=50):
        """Calcula la matriz simétrica P de probabilidades conjuntas en alta dimensión."""
        N, D = X.shape
        # Matriz de distancias euclidianas al cuadrado: ||x_i - x_j||^2
        sum_X = np.sum(np.square(X), axis=1)
        D_sq = np.add(np.add(-2 * np.dot(X, X.T), sum_X).T, sum_X)
        np.fill_diagonal(D_sq, 0.0)
        D_sq = np.maximum(D_sq, 0.0)

        P = np.zeros((N, N), dtype=np.float64)
        log_perp_target = np.log(self.perplexity)

        # Búsqueda binaria independiente para cada muestra i
        for i in range(N):
            beta_min = -float('inf')
            beta_max = float('inf')
            beta = 1.0  # beta = 1 / (2 * sigma_i^2)

            # Distancias a los demás puntos
            d_i = D_sq[i, np.concatenate([np.arange(0, i), np.arange(i + 1, N)])]

            for _ in range(max_iter):
                # Probabilidades no normalizadas
                exp_d = np.exp(-d_i * beta)
                sum_exp = np.sum(exp_d)
                if sum_exp < 1e-15:
                    sum_exp = 1e-15

                # Entropía de Shannon: H = ln(sum_exp) + beta * sum(d * exp_d) / sum_exp
                H = np.log(sum_exp) + beta * np.sum(d_i * exp_d) / sum_exp
                H_diff = H - log_perp_target

                if abs(H_diff) < tol:
                    break

                if H_diff > 0:
                    beta_min = beta
                    beta = beta * 2.0 if beta_max == float('inf') else (beta + beta_max) / 2.0
                else:
                    beta_max = beta
                    beta = beta / 2.0 if beta_min == -float('inf') else (beta + beta_min) / 2.0

            # Guardar probabilidades condicionales normalizadas
            exp_d_all = np.exp(-D_sq[i] * beta)
            exp_d_all[i] = 0.0
            sum_all = np.sum(exp_d_all)
            P[i] = exp_d_all / (sum_all if sum_all > 1e-15 else 1e-15)

        # Simetrización: p_ij = (p_j|i + p_i|j) / (2N)
        P_simetrica = (P + P.T) / (2.0 * N)
        return np.maximum(P_simetrica, 1e-12)

    def fit_transform(self, X):
        """Ajusta t-SNE y retorna las coordenadas bidimensionales proyectadas."""
        N, D = X.shape
        rng = np.random.RandomState(self.random_state)

        # 1. Matriz de afinidades en alta dimensión P
        P = self._calcular_probabilidades_p(X)

        # Aplicar Early Exaggeration para forzar formación temprana de clústeres
        P_exagerada = P * self.early_exaggeration

        # 2. Inicialización latente pequeña gaussiana
        Y = rng.normal(0.0, 1e-4, size=(N, self.n_components))
        Y_vel = np.zeros_like(Y)
        Y_prev = Y.copy()

        # Parámetros de momento
        momentum_inicial = 0.5
        momentum_final = 0.8
        iter_fin_exaggeration = 100

        for it in range(self.n_iter):
            # Matriz de distancias al cuadrado en baja dimensión
            sum_Y = np.sum(np.square(Y), axis=1)
            dist_Y_sq = np.add(np.add(-2 * np.dot(Y, Y.T), sum_Y).T, sum_Y)
            np.fill_diagonal(dist_Y_sq, 0.0)

            # Afinidad de Cauchy (t-Student 1 gl): w_ij = 1 / (1 + ||y_i - y_j||^2)
            W = 1.0 / (1.0 + dist_Y_sq)
            np.fill_diagonal(W, 0.0)
            sum_W = np.sum(W)
            Q = np.maximum(W / (sum_W if sum_W > 1e-15 else 1e-15), 1e-12)

            # Matriz P activa (exagerada o estándar)
            P_activa = P_exagerada if it < iter_fin_exaggeration else P

            # Gradiente analítico exacto: 4 * sum_j (p_ij - q_ij) * w_ij * (y_i - y_j)
            PQ_diff = P_activa - Q
            grad = np.zeros_like(Y)
            for i in range(N):
                # Multiplicación ponderada vectorizada
                factores = (PQ_diff[i] * W[i])[:, np.newaxis]
                grad[i] = 4.0 * np.sum(factores * (Y[i] - Y), axis=0)

            # Actualización con momento
            momentum = momentum_inicial if it < iter_fin_exaggeration else momentum_final
            Y_vel = momentum * Y_vel - self.lr * grad
            Y += Y_vel

            # Centrar coordenadas para evitar derivas numéricas
            Y -= np.mean(Y, axis=0)

        self.embedding_ = Y
        # Divergencia KL final
        self.kl_divergence_ = np.sum(P * np.log(np.maximum(P / Q, 1e-12)))
        return Y


class UMAP_MinimoPuro:
    """
    Implementación minimalista pedagógica de los fundamentos matemáticos de UMAP.
    Construye el grafo simplicial difuso con conectividad rho_i,
    aplica la unión algebraica difusa y optimiza la Entropía Cruzada Difusa.
    """
    def __init__(self, n_components=2, n_neighbors=15, min_dist=0.1, n_iter=200, lr=1.0, random_state=42):
        self.n_components = n_components
        self.n_neighbors = n_neighbors
        self.min_dist = min_dist
        self.n_iter = n_iter
        self.lr = lr
        self.random_state = random_state
        # Coeficientes a y b calibrados para aproximar min_dist = 0.1
        self.a = 1.5769
        self.b = 0.8950
        self.embedding_ = None

    def _construir_grafo_difuso(self, X):
        N = X.shape[0]
        # Distancias euclidianas
        sum_X = np.sum(np.square(X), axis=1)
        D_mat = np.sqrt(np.maximum(np.add(np.add(-2 * np.dot(X, X.T), sum_X).T, sum_X), 0.0))
        np.fill_diagonal(D_mat, float('inf'))

        P_cond = np.zeros((N, N), dtype=np.float64)
        target = np.log2(self.n_neighbors)

        for i in range(N):
            # rho_i: distancia al vecino más cercano
            dist_ordenadas = np.sort(D_mat[i])
            rho_i = dist_ordenadas[0]
            if rho_i == float('inf'):
                rho_i = 0.0

            # Búsqueda binaria de sigma_i tal que sum(exp(-(d - rho)/sigma)) = log2(k)
            sigma_min, sigma_max, sigma = 1e-4, 100.0, 1.0
            vecinos_dist = dist_ordenadas[:self.n_neighbors]
            for _ in range(30):
                val = np.sum(np.exp(-np.maximum(0.0, vecinos_dist - rho_i) / sigma))
                if abs(val - target) < 1e-4:
                    break
                if val > target:
                    sigma_max = sigma
                    sigma = (sigma + sigma_min) / 2.0
                else:
                    sigma_min = sigma
                    sigma = (sigma + sigma_max) / 2.0

            # P_j|i
            d_reales = D_mat[i].copy()
            d_reales[i] = 0.0
            P_cond[i] = np.exp(-np.maximum(0.0, d_reales - rho_i) / max(sigma, 1e-4))
            P_cond[i, i] = 0.0

        # Unión difusa: p_ij = p_i|j + p_j|i - p_i|j * p_j|i
        P_difuso = P_cond + P_cond.T - P_cond * P_cond.T
        return np.maximum(P_difuso, 1e-12)

    def fit_transform(self, X):
        N = X.shape[0]
        rng = np.random.RandomState(self.random_state)
        P = self._construir_grafo_difuso(X)

        # Inicialización latente
        Y = rng.normal(0.0, 1.0, size=(N, self.n_components))

        for it in range(self.n_iter):
            # Distancias en baja dimensión
            sum_Y = np.sum(np.square(Y), axis=1)
            dist_sq = np.maximum(np.add(np.add(-2 * np.dot(Y, Y.T), sum_Y).T, sum_Y), 1e-12)
            
            # Afinidad UMAP: q_ij = (1 + a * d^(2b))^-1
            Q = 1.0 / (1.0 + self.a * (dist_sq**self.b))
            np.fill_diagonal(Q, 0.0)

            # Gradiente de Entropía Cruzada Difusa:
            # Atracción:  - 2b * a * d^(2(b-1)) * Q * p_ij * (y_i - y_j)
            # Repulsión:  + 2b * (1 - p_ij) / ( (1 - Q + 1e-4) * (1 + a * d^(2b)) ) ...
            grad = np.zeros_like(Y)
            for i in range(N):
                diff = Y[i] - Y
                d_sq_i = dist_sq[i][:, np.newaxis]
                # Factor de fuerza atractiva
                f_atr = (P[i] * Q[i])[:, np.newaxis]
                # Factor de fuerza repulsiva
                f_rep = ((1.0 - P[i]) * Q[i] / (1.0 - Q[i] + 1e-4))[:, np.newaxis]
                
                fuerza = 2.0 * self.b * (f_atr - f_rep) / (d_sq_i + 1e-4)
                grad[i] = np.sum(fuerza * diff, axis=0)

            tasa_actual = self.lr * (1.0 - it / self.n_iter)
            Y -= tasa_actual * grad
            Y -= np.mean(Y, axis=0)

        self.embedding_ = Y
        return Y


# =====================================================================
# Verificación Numérica: Desenrollado de Manifolds No Lineales
# =====================================================================
if __name__ == "__main__":
    np.random.seed(42)

    # Generación de 3 clusters gaussianos bien diferenciados en ℝ^10
    N_por_clase = 30
    c1 = np.random.randn(N_por_clase, 10) + np.array([5.0] * 10)
    c2 = np.random.randn(N_por_clase, 10) - np.array([5.0] * 10)
    c3 = np.random.randn(N_por_clase, 10) + np.array([5.0, -5.0] * 5)

    X_test = np.vstack([c1, c2, c3])
    y_test = np.repeat([0, 1, 2], N_por_clase)

    print("=== Validación Numérica: t-SNE Puro vs UMAP Puro en ℝ^10 -> ℝ^2 ===")
    
    tsne_model = tSNE_Puro(n_components=2, perplexity=15.0, n_iter=200, lr=150.0, random_state=42)
    Y_tsne = tsne_model.fit_transform(X_test)
    print(f"t-SNE Divergencia KL final alcanzada: {tsne_model.kl_divergence_:.4f}")
    print(f"Coordenadas latentes t-SNE (shape {Y_tsne.shape}): Varianza eje 1={np.var(Y_tsne[:,0]):.2f}, eje 2={np.var(Y_tsne[:,1]):.2f}")

    umap_model = UMAP_MinimoPuro(n_components=2, n_neighbors=10, min_dist=0.1, n_iter=150, random_state=42)
    Y_umap = umap_model.fit_transform(X_test)
    print(f"Coordenadas latentes UMAP (shape {Y_umap.shape}): Varianza eje 1={np.var(Y_umap[:,0]):.2f}, eje 2={np.var(Y_umap[:,1]):.2f}")
```

---

## 7. Directrices de Razonamiento para los Modelos de Inteligencia Artificial en Prig IDE

Cuando un modelo de lenguaje en Prig IDE oriente, diagnostique o ejecute visualizaciones de alta dimensión con **t-SNE** (`sklearn.manifold.TSNE`, `openTSNE`, `fitsne`) o **UMAP** (`umap.UMAP`), aplicará de manera estricta las siguientes directrices técnicas:

1. **Pre-reducción Lineal Obligatoria con PCA:**
   - En conjuntos de datos con $D > 50$ (como embeddings de texto, microarrays de expresión génica o representaciones de CNN), **anteponer siempre un paso de PCA a 30 o 50 dimensiones**.
   - Justificación matemática: la distancia euclidiana en $D > 100$ sufre de la maldición de la dimensionalidad (las distancias se vuelven equirrelativas), y calcular $k$-NN directamente en $\mathbb{R}^D$ es computacionalmente prohibitivo e introduce ruido de alta frecuencia.

2. **Advertencia de Interpretación Causal en t-SNE:**
   - **Prohibición de inferir distancias globales:** Advertir explícitamente al usuario que la distancia euclidiana entre clústeres separados en un gráfico de t-SNE **no tiene ningún significado físico ni métrico**. Dos clústeres pueden estar a 10 unidades de distancia en t-SNE simplemente por artefactos del proceso de empaquetamiento estocástico.
   - Si el usuario necesita estudiar trayectorias evolutivas, linajes biológicos continuos o relaciones inter-clúster, recomendar **UMAP** con `n_neighbors` elevado ($30 \le k \le 100$) o difusión armónica (*Diffusion Maps*).

3. **Inferencia Fuera de Muestra (`transform`):**
   - Recordar que la implementación canónica de t-SNE en scikit-learn **carece del método `transform()`**. Requiere reajustar todo el dataset si llegan nuevas muestras.
   - Si el pipeline requiere proyectar dinámicamente nuevos datos de prueba en tiempo de ejecución (por ejemplo en un sistema de búsqueda visual o recomendación en producción), prescribir **UMAP**, ya que su grafo simplicial y optimización local admiten `reducer.transform(X_nuevo)` de manera directa.

4. **Protocolo de Calibración de Hiperparámetros:**
   - **Si los clústeres se fragmentan en cientos de micro-islas artificiales:** La perplejidad (en t-SNE) o `n_neighbors` (en UMAP) es demasiado baja. Incrementar gradualmente a $30 - 50$.
   - **Si los datos forman una esfera o disco amorfo indiferenciado:**
     - En t-SNE: Incrementar el número de iteraciones (`max_iter >= 1000`) o subir la tasa de aprendizaje (`learning_rate='auto'`).
     - En UMAP: Reducir `min_dist` a $0.01$ o $0.05$ para permitir que los clústeres se compacten con mayor densidad.
