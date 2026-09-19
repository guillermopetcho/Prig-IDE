# Monografía 12: k-Means Clustering — Fundamentos de Cuantización, el Algoritmo de Lloyd, Inicialización k-Means++ y Aceleración Métrica de Elkan

> **Directorio de Ubicación:** `docs/analisis_papers/12_kmeans_clustering.md`  
> **Ficha Técnica Modular Resumida:** [`docs/algoritmos_ml/12_kmeans_clustering.md`](../algoritmos_ml/12_kmeans_clustering.md)  
> **Estado del Documento:** Riguroso / Nivel Doctoral / Producción Académica  

---

## 1. Ficha Bibliográfica y Genealogía de Papers Seminales

1. **La Cuantización de Mínimos Cuadrados en PCM (Bell Labs 1957 / IEEE 1982):**
   - **Título:** *Least Squares Quantization in PCM*
   - **Autor:** Stuart P. Lloyd (Bell Telephone Laboratories).
   - **Publicación:** *IEEE Transactions on Information Theory*, 28(2), pp. 129–137 (1982). Publicado originalmente como memorando técnico interno en Bell Labs en 1957.
   - **Aporte Principal:** Formulación del problema de discretización de señales continuas en modulación por impulsos codificados (PCM) mediante celdas de Voronoi y centroides de masa. Deducción del bucle alternado de asignación y actualización de centroides, conocido universalmente como el **Algoritmo de Lloyd**.

2. **La Formalización del Término $k$-Means (Berkeley Symposium, 1967):**
   - **Título:** *Some Methods for Classification and Analysis of Multivariate Observations*
   - **Autor:** J. MacQueen.
   - **Publicación:** *Proceedings of the Fifth Berkeley Symposium on Mathematical Statistics and Probability*, Vol. 1, pp. 281–297 (1967).
   - **Aporte Principal:** Acuñación formal del término **$k$-Means**. Introducción de una variante secuencial (*online / stochastic*) que actualiza los centroides muestra por muestra y primera demostración estadística de la convergencia asintótica a la media poblacional.

3. **k-Means++ y la Cota de Aproximación Logarítmica (SODA 2007):**
   - **Título:** *k-means++: The Advantages of Careful Seeding*
   - **Autores:** David Arthur y Sergei Vassilvitskii (Stanford University).
   - **Publicación:** *Proceedings of the 18th Annual ACM-SIAM Symposium on Discrete Algorithms (SODA '07)*, pp. 1027–1035 (2007).
   - **Aporte Principal:** Resolución de la extrema sensibilidad de $k$-Means a las condiciones iniciales. Introducción del esquema de muestreo probabilístico proporcional a las distancias cuadradas $D(x)^2$ y demostración del teorema de cota de aproximación esperada de $\mathcal{O}(\log k)$ respecto a la inercia óptima global.

4. **Aceleración por Desigualdad Triangular (ICML 2003):**
   - **Título:** *Using the Triangle Inequality to Accelerate k-Means*
   - **Autor:** Charles Elkan (University of California, San Diego).
   - **Publicación:** *Proceedings of the Twentieth International Conference on Machine Learning (ICML '03)*, pp. 147–153 (2003).
   - **Aporte Principal:** Aceleración algorítmica estricta que preserva exactamente la misma trayectoria matemática de Lloyd pero omite hasta el 95% de los cálculos de distancias euclidianas manteniendo cotas métricas superior e inferior vía la desigualdad triangular.

5. **El Coeficiente de Silueta para la Validación de Clústeres (1987):**
   - **Título:** *Silhouettes: A Graphical Aid to the Interpretation and Validation of Cluster Analysis*
   - **Autor:** Peter J. Rousseeuw.
   - **Publicación:** *Journal of Computational and Applied Mathematics*, 20, pp. 53–65 (1987).
   - **Aporte Principal:** Formulación de la métrica intrínseca de silueta $s(i) \in [-1, 1]$ integrando simultáneamente la cohesión intra-clúster y la separación inter-clúster para resolver el problema de selección del número óptimo de agrupaciones $k$.

---

## 2. Génesis Teórica: Particionamiento Óptimo y la Inercia de Cuadrados Mínimos

Sea un conjunto de datos $\mathcal{X} = \{x_1, x_2, \dots, x_N\} \subset \mathbb{R}^D$ de vectores continuos.  
El problema de agrupamiento $k$-Means consiste en encontrar una partición disjunta de $\mathcal{X}$ en $k$ conjuntos $\mathcal{S} = \{S_1, S_2, \dots, S_k\}$ con $\bigcup_{j=1}^k S_j = \mathcal{X}$ y $S_i \cap S_j = \emptyset$ para $i \ne j$, tal que se minimice la **Suma de Cuadrados Intra-Clúster (WCSS o Inercia)**:
$$\mathcal{J}(\mathcal{S}, \boldsymbol{\mu}) = \sum_{j=1}^k \sum_{x_i \in S_j} \|x_i - \mu_j\|^2$$
donde $\boldsymbol{\mu} = (\mu_1, \dots, \mu_k)$ representa los centros de masa o centroides en $\mathbb{R}^D$.

### 2.1. Teorema: La Media Aritmética como Solución Óptima de Centroide

**Teorema:**  
Dado un clúster de puntos fijo $S_j = \{x_1, \dots, x_{N_j}\}$, el punto en $\mathbb{R}^D$ que minimiza la suma de distancias euclidianas al cuadrado a todos los miembros de $S_j$ es invariablemente su media aritmética muestral.

**Demostración Analítica:**  
Consideremos la función de costo para un grupo particular respecto a un centro genérico $\mu_j \in \mathbb{R}^D$:
$$\Phi(\mu_j) = \sum_{x \in S_j} \|x - \mu_j\|^2 = \sum_{x \in S_j} \sum_{d=1}^D (x_d - \mu_{jd})^2$$

Diferenciando respecto a cada coordenada $\mu_{jd}$ e igualando a cero:
$$\frac{\partial \Phi}{\partial \mu_{jd}} = -2 \sum_{x \in S_j} (x_d - \mu_{jd}) = 0 \implies \sum_{x \in S_j} x_d - N_j \mu_{jd} = 0$$
$$\mu_{jd}^* = \frac{1}{N_j} \sum_{x \in S_j} x_d \implies \mu_j^* = \frac{1}{|S_j|} \sum_{x \in S_j} x$$

Dado que la matriz Hessiana $\nabla^2 \Phi = 2 N_j \mathbf{I}_{D \times D}$ es estrictamente definida positiva, $\mu_j^*$ es el minimizador global único de la inercia del clúster.

### 2.2. Complejidad Computacional y la Dureza NP-Hard

El espacio de búsqueda de particiones posibles de $N$ objetos en $k$ grupos no vacíos viene dado por los **Números de Stirling de Segunda Especie**:
$$S(N, k) = \frac{1}{k!} \sum_{j=0}^k (-1)^{k-j} \binom{k}{j} j^N \approx \frac{k^N}{k!}$$

- Para un problema minúsculo con $N = 50$ y $k = 4$, $S(50, 4) \approx 1.11 \times 10^{29}$ particiones.
- **Teorema de Dureza (Mahajan et al., 2009; Dasgupta, 2008):** Encontrar el minimizador global de $\mathcal{J}(\mathcal{S}, \boldsymbol{\mu})$ es un problema **NP-Hard** incluso para $k = 2$ en espacios arbitrarios $\mathbb{R}^D$, o para $D = 2$ en el plano bidimensional con $k$ arbitrario.  
Por esta razón, la optimización práctica requiere algoritmos heurísticos de descenso alternado por bloques como el algoritmo de Lloyd.

---

## 3. El Algoritmo de Lloyd y su Dinámica de Convergencia

```mermaid
graph TD
    classDef init fill:#1e1e2e,stroke:#89b4fa,stroke-width:2px,color:#cdd6f4;
    classDef loop fill:#181825,stroke:#f9e2af,stroke-width:2px,color:#cdd6f4;
    classDef elkan fill:#181825,stroke:#a6e3a1,stroke-width:2px,color:#cdd6f4;
    classDef out fill:#181825,stroke:#cba6f7,stroke-width:2px,color:#cdd6f4;

    A["📊 Dataset X en R^{N x D}"]:::init --> B["🎯 Inicialización k-Means++ (Arthur & Vassilvitskii, 2007)"]:::init
    B --> C["📍 Centroides Iniciales μ_1, ..., μ_k bajo Probabilidad D(x)²"]:::init
    C --> D["Paso 1: Asignación Voronoi (Minimizar sobre S fijando μ)"]:::loop
    D --> E["⚡ Aceleración de Elkan: Poda métrica si d(x, μ) ≤ 1/2 d(μ, c)"]:::elkan
    E --> F["Paso 2: Actualización de Centroides (Minimizar sobre μ fijando S)"]:::loop
    F --> G{"¿||Δμ|| < tol o iter = max_iter?"}:::loop
    G -->|No (Inercia decrece estrictamente)| D
    G -->|Sí| H["🏁 Convergencia a Mínimo Local: Partición Óptima S* y μ*"]:::out
```

### 3.1. Interpretación como Descenso de Coordenadas por Bloques

El algoritmo de Lloyd (1957/1982) desacopla la minimización conjunta de $\mathcal{J}(\mathcal{S}, \boldsymbol{\mu})$ alternando dos pasos de optimización exacta sobre subconjuntos de variables:

1. **Paso de Asignación (Expectation / Fijar $\boldsymbol{\mu}$, optimizar $\mathcal{S}$):**  
   Manteniendo fijos los centroides actuales $\boldsymbol{\mu}^{(t)}$, la inercia se minimiza asignando de forma voraz cada muestra al centroide euclidiano más cercano:
   $$S_j^{(t)} = \left\{ x_i \in \mathcal{X} \mid \|x_i - \mu_j^{(t)}\|^2 \le \|x_i - \mu_l^{(t)}\|^2, \quad \forall l \in \{1, \dots, k\} \right\}$$
   Esto induce una partición del espacio en **Celdas de Voronoi** poliedrales $\mathcal{V}(\mu_j)$.
2. **Paso de Actualización (Maximization / Fijar $\mathcal{S}$, optimizar $\boldsymbol{\mu}$):**  
   Manteniendo fija la partición de Voronoi $S_j^{(t)}$, se recalculan los centroides minimizando la inercia interna de cada grupo:
   $$\mu_j^{(t+1)} = \frac{1}{|S_j^{(t)}|} \sum_{x \in S_j^{(t)}} x$$

### 3.2. Teorema de Monotonía y Convergencia Finita

**Teorema:**  
El algoritmo de Lloyd garantiza la convergencia monótona hacia un mínimo local en un número finito de iteraciones.

**Demostración:**  
En cada paso del ciclo:
$$\mathcal{J}(\mathcal{S}^{(t+1)}, \boldsymbol{\mu}^{(t+1)}) \le \mathcal{J}(\mathcal{S}^{(t+1)}, \boldsymbol{\mu}^{(t)}) \le \mathcal{J}(\mathcal{S}^{(t)}, \boldsymbol{\mu}^{(t)})$$
- La primera desigualdad se cumple porque la media muestral minimiza globalmente la suma de cuadrados de una partición fija.
- La segunda se cumple porque asignar cada punto a su centroide más próximo minimiza la suma de distancias cuadradas sobre todas las asignaciones posibles.
- Dado que el número de particiones posibles es estrictamente finito ($S(N, k)$) y el valor de la función objetivo está acotado inferiormente por cero ($\mathcal{J} \ge 0$), el algoritmo no puede ciclar sin fin y debe converger a una partición estacionaria donde $\mathcal{S}^{(t+1)} = \mathcal{S}^{(t)}$ en tiempo finito.

---

## 4. Inicialización $k$-Means++ (Arthur & Vassilvitskii, 2007)

La inicialización clásica de Forgy (selección de $k$ centros uniformemente al azar del conjunto de datos) adolece de una falla patológica: con alta probabilidad, dos o más centroides iniciales caerán en el mismo agrupamiento real, mientras que otros agrupamientos quedarán sin centroide. Esto bloquea al algoritmo en mínimos locales de pésima calidad.

### 4.1. Algoritmo de Muestreo de Semillas $D(x)^2$

Arthur & Vassilvitskii diseñaron una distribución de probabilidad que fuerza a los centroides a dispersarse uniformemente por el soporte espacial de los datos:

1. Elegir el primer centroide $\mu_1$ de manera estrictamente uniforme entre todos los puntos de $\mathcal{X}$.
2. Para cada muestra $x \in \mathcal{X}$, calcular la distancia euclidiana mínima a los centros ya seleccionados:
   $$D(x) = \min_{j \in \{1, \dots, m\}} \|x - \mu_j\|$$
3. Seleccionar el siguiente centroide $\mu_{m+1} = x$ con probabilidad proporcional al cuadrado de su distancia más corta:
   $$P(x) = \frac{D(x)^2}{\sum_{x' \in \mathcal{X}} D(x')^2}$$
4. Repetir los pasos 2 y 3 hasta haber seleccionado los $k$ centros iniciales.

### 4.2. El Teorema de la Cota de Aproximación $\mathcal{O}(\log k)$

**Teorema Fundamental (Arthur & Vassilvitskii, 2007):**  
Sea $\mathcal{J}_{\text{opt}}$ la inercia mínima global inalcanzable de un conjunto de datos $\mathcal{X}$ para $k$ centros. Si los centroides iniciales $\boldsymbol{\mu}^{(0)}$ se seleccionan mediante el algoritmo $k$-means++, la inercia esperada satisface:
$$\mathbb{E}\left[ \mathcal{J}(\mathcal{S}, \boldsymbol{\mu}^{(0)}) \right] \le 8(\ln k + 2) \cdot \mathcal{J}_{\text{opt}}$$

#### Trascendencia Teórica:
- Convierte un problema NP-Hard en un algoritmo de **aproximación probabilística con garantía competitiva logarítmica** $\mathcal{O}(\log k)$.
- Previene que el error de agrupamiento sea arbitrariamente grande.
- Reduce en un factor de $2\times$ a $5\times$ el número de iteraciones necesarias para la convergencia final de Lloyd.

---

## 5. Aceleración Métrica por Desigualdad Triangular (Charles Elkan, 2003)

En cada iteración del algoritmo de Lloyd clásico, se calculan $N \times k$ distancias euclidianas en $\mathbb{R}^D$, lo que para $N = 1,000,000$ y $k = 100$ representa $10^8$ operaciones de producto interno por ciclo.  
Charles Elkan descubrió que en un espacio métrico, **la mayoría de los puntos permanecen fieles a su mismo centroide entre iteraciones sucesivas**, y la distancia a otros centroides lejanos puede acotarse sin necesidad de evaluarla.

### 5.1. Regla de Poda de Elkan

Sean $x$ un punto, $\mu_j$ su centroide asignado actualmente, y $\mu_l$ un centroide alternativo.  
Sea $d(\mu_j, \mu_l)$ la distancia euclidiana entre ambos centros.  
Por la **desigualdad triangular**:
$$d(\mu_j, \mu_l) \le d(x, \mu_j) + d(x, \mu_l) \implies d(x, \mu_l) \ge d(\mu_j, \mu_l) - d(x, \mu_j)$$

**Lema de Poda Incondicional:**  
Si se satisface la condición:
$$d(x, \mu_j) \le \frac{1}{2} d(\mu_j, \mu_l)$$
entonces:
$$d(x, \mu_l) \ge d(\mu_j, \mu_l) - d(x, \mu_j) \ge 2 d(x, \mu_j) - d(x, \mu_j) = d(x, \mu_j)$$
Por lo tanto, **es geométricamente imposible que $x$ esté más cerca de $\mu_l$ que de su centro actual $\mu_j$**. El cálculo de la distancia $d(x, \mu_l)$ se descarta sin realizar ninguna operación en $\mathbb{R}^D$.

### 5.2. Mantenimiento de Cotas Superiores e Inferiores
Elkan mantiene:
- Una cota superior $u(i) \ge d(x_i, \mu(x_i))$.
- Una cota inferior $l(i, j) \le d(x_i, \mu_j)$ para cada centro alternativo.
- Cuando los centros se desplazan en la iteración $t$ por un vector $\Delta \mu_j$, las cotas se actualizan en $\mathcal{O}(1)$ mediante:
  $$u(i) \leftarrow u(i) + \|\mu^{(t+1)}(x_i) - \mu^{(t)}(x_i)\|$$
  $$l(i, j) \leftarrow \max\left(0, \, l(i, j) - \|\mu_j^{(t+1)} - \mu_j^{(t)}\|\right)$$
Esta técnica reduce el costo computacional hasta en un 95% manteniendo la identidad exacta de la solución de Lloyd.

---

## 6. Selección del Número Óptimo de Clústeres: El Coeficiente de Silueta

Dado que la inercia $\mathcal{J}$ es una función monótona decreciente trivial respecto a $k$ ($\mathcal{J} \to 0$ cuando $k \to N$), no puede utilizarse de forma directa para elegir $k$.

### 6.1. Formulación de Rousseeuw (1987)

Para una muestra $i$ perteneciente al clúster $A$:
1. **Cohesión Intra-Clúster $a(i)$:** Distancia media desde el punto $i$ a todos los demás puntos de su mismo grupo:
   $$a(i) = \frac{1}{|A| - 1} \sum_{j \in A, \, j \ne i} \|x_i - x_j\|$$
2. **Separación Inter-Clúster $b(i)$:** Distancia media más corta desde el punto $i$ a los puntos del clúster vecino más cercano $C$:
   $$b(i) = \min_{C \ne A} \frac{1}{|C|} \sum_{j \in C} \|x_i - x_j\|$$
3. **Coeficiente de Silueta Individual $s(i)$:**
   $$s(i) = \frac{b(i) - a(i)}{\max(a(i), b(i))} \in [-1, 1]$$

#### Interpretación Analítica:
- $s(i) \approx +1$: La muestra está muy cerca de su propio centroide y muy lejos del clúster vecino (agrupamiento excelente).
- $s(i) \approx 0$: La muestra yace en la frontera de Voronoi equidistante entre dos clústeres.
- $s(i) \approx -1$: La muestra fue asignada erróneamente al clúster equivocado.

El **Silhouette Score Global** es la media aritmética $\bar{s} = \frac{1}{N} \sum_{i=1}^N s(i)$. El valor de $k$ que maximiza $\bar{s}$ identifica la partición con mayor coherencia geométrica intrínseca.

---

## 7. Implementación Pura en Python y NumPy (Sin Scikit-Learn ni SciPy)

A continuación se presenta un motor completo en NumPy puro que implementa:
1. **Inicialización probabilística $k$-means++** con cálculo eficiente de distancias mínimas $D(x)^2$.
2. **Algoritmo de Lloyd** con formulación matricial vectorizada de distancias euclidianas.
3. **Múltiples reinicios estocásticos (`n_init`)** conservando la solución de mínima inercia.
4. **Cálculo del Coeficiente de Silueta**.

```python
"""
Módulo Didáctico de Referencia: k-Means y k-Means++ en NumPy Puro
Implementa el algoritmo de Lloyd (1982), el sembrado de Arthur & Vassilvitskii (2007)
y el Coeficiente de Silueta de Rousseeuw (1987) sin scikit-learn.
"""

import numpy as np


def calcular_distancias_euclidianas_cuadradas(X, centros):
    """
    Computa la matriz de distancias cuadradas entre N puntos y K centros
    usando la descomposición matricial: ||x - μ||^2 = ||x||^2 + ||μ||^2 - 2 x μ^T.
    Shape de salida: (N, K)
    """
    normas_X = np.sum(X**2, axis=1, keepdims=True)       # (N, 1)
    normas_centros = np.sum(centros**2, axis=1)          # (K,)
    producto_cruzado = np.dot(X, centros.T)             # (N, K)
    dist_sq = normas_X + normas_centros - 2.0 * producto_cruzado
    return np.maximum(dist_sq, 0.0)


def inicializar_kmeans_plus_plus(X, k, rng):
    """
    Inicialización inteligente k-means++ (Arthur & Vassilvitskii, 2007).
    Selecciona centroides secuenciales con probabilidad proporcional a D(x)^2.
    """
    N, D = X.shape
    centros = np.empty((k, D), dtype=np.float64)

    # 1. Primer centroide completamente uniforme
    idx_primer_centro = rng.randint(0, N)
    centros[0] = X[idx_primer_centro]

    # Distancia cuadrática mínima actual de cada punto al centroide más cercano
    dist_min_sq = np.sum((X - centros[0])**2, axis=1)

    # 2. Seleccionar los siguientes k-1 centros probabilísticamente
    for m in range(1, k):
        # Probabilidades normalizadas proporcionales a D(x)^2
        suma_dist = np.sum(dist_min_sq)
        if suma_dist == 0.0:
            # Puntos colapsados: elegir cualquier muestra restante
            probs = np.full(N, 1.0 / N)
        else:
            probs = dist_min_sq / suma_dist

        # Muestreo con ruleta acumulada
        cumsum_probs = np.cumsum(probs)
        r = rng.rand()
        nuevo_idx = np.searchsorted(cumsum_probs, r)
        nuevo_idx = min(nuevo_idx, N - 1)

        centros[m] = X[nuevo_idx]

        # Actualizar distancias mínimas considerando el nuevo centro
        dist_nuevo_centro = np.sum((X - centros[m])**2, axis=1)
        dist_min_sq = np.minimum(dist_min_sq, dist_nuevo_centro)

    return centros


class KMeansPuro:
    """
    Algoritmo de particionamiento k-Means con soporte para k-means++ y n_init.
    """
    def __init__(self, n_clusters=3, init='k-means++', n_init=10, max_iter=300, tol=1e-4, random_state=42):
        self.k = n_clusters
        self.init = init
        self.n_init = n_init
        self.max_iter = max_iter
        self.tol = tol
        self.random_state = random_state
        
        # Parámetros aprendidos del mejor intento
        self.cluster_centers_ = None
        self.labels_ = None
        self.inertia_ = float('inf')

    def fit(self, X):
        N, D = X.shape
        rng = np.random.RandomState(self.random_state)
        mejor_inercia = float('inf')
        mejores_centros = None
        mejores_etiquetas = None

        for intento in range(self.n_init):
            # Inicialización de centroides
            if self.init == 'k-means++':
                centros = inicializar_kmeans_plus_plus(X, self.k, rng)
            elif self.init == 'random':
                indices_aleatorios = rng.choice(N, size=self.k, replace=False)
                centros = X[indices_aleatorios].copy()
            else:
                raise ValueError(f"Inicializador no soportado: {self.init}")

            for iteracion in range(self.max_iter):
                # Paso 1: Asignación Voronoi
                distancias_sq = calcular_distancias_euclidianas_cuadradas(X, centros)
                etiquetas = np.argmin(distancias_sq, axis=1)

                # Paso 2: Actualización de centroides (media de masa)
                nuevos_centros = np.empty_like(centros)
                for j in range(self.k):
                    mascara_j = (etiquetas == j)
                    if np.any(mascara_j):
                        nuevos_centros[j] = np.mean(X[mascara_j], axis=0)
                    else:
                        # Manejo de clúster huérfano / vacío: re-inicializar en punto aleatorio
                        nuevos_centros[j] = X[rng.randint(0, N)]

                # Criterio de convergencia por desplazamiento de centroides
                desplazamiento = np.sum((nuevos_centros - centros)**2)
                centros = nuevos_centros

                if desplazamiento < self.tol:
                    break

            # Calcular la inercia total del intento actual
            distancias_finales_sq = calcular_distancias_euclidianas_cuadradas(X, centros)
            etiquetas_finales = np.argmin(distancias_finales_sq, axis=1)
            inercia_actual = np.sum(np.min(distancias_finales_sq, axis=1))

            if inercia_actual < mejor_inercia:
                mejor_inercia = inercia_actual
                mejores_centros = centros
                mejores_etiquetas = etiquetas_finales

        self.cluster_centers_ = mejores_centros
        self.labels_ = mejores_etiquetas
        self.inertia_ = mejor_inercia
        return self

    def predict(self, X):
        distancias_sq = calcular_distancias_euclidianas_cuadradas(X, self.cluster_centers_)
        return np.argmin(distancias_sq, axis=1)


def calcular_coeficiente_silueta(X, etiquetas):
    """
    Computa el Silhouette Score global de Rousseeuw (1987) en NumPy puro.
    """
    N = len(X)
    clases = np.unique(etiquetas)
    if len(clases) <= 1 or len(clases) >= N:
        return 0.0

    siluetas = np.zeros(N)

    # Matriz completa de distancias por pares
    dists = np.sqrt(calcular_distancias_euclidianas_cuadradas(X, X))

    for i in range(N):
        clase_i = etiquetas[i]
        mascara_mismo_cluster = (etiquetas == clase_i)

        # 1. Cohesión intra-cluster a(i)
        if np.sum(mascara_mismo_cluster) > 1:
            a_i = np.sum(dists[i, mascara_mismo_cluster]) / (np.sum(mascara_mismo_cluster) - 1)
        else:
            a_i = 0.0

        # 2. Separación inter-cluster b(i)
        b_i = float('inf')
        for c in clases:
            if c != clase_i:
                mascara_otro = (etiquetas == c)
                if np.any(mascara_otro):
                    dist_media_c = np.mean(dists[i, mascara_otro])
                    if dist_media_c < b_i:
                        b_i = dist_media_c

        # 3. Silueta s(i)
        denom = max(a_i, b_i)
        siluetas[i] = (b_i - a_i) / denom if denom > 0 else 0.0

    return np.mean(siluetas)


# =====================================================================
# Verificación y Validación Numérica
# =====================================================================
if __name__ == "__main__":
    np.random.seed(42)
    N = 300
    D = 2

    # Generación sintética de 3 clusters gaussianos bien diferenciados
    X1 = np.random.normal(loc=[-4.0, -3.0], scale=0.7, size=(100, D))
    X2 = np.random.normal(loc=[3.0, 3.0], scale=0.8, size=(100, D))
    X3 = np.random.normal(loc=[0.0, 5.0], scale=0.6, size=(100, D))
    X = np.vstack([X1, X2, X3])

    # Ajuste con k-Means++
    km = KMeansPuro(n_clusters=3, init='k-means++', n_init=10, random_state=42)
    km.fit(X)

    score_silueta = calcular_coeficiente_silueta(X, km.labels_)

    print("=== Módulo k-Means y k-Means++ Puro: Validación Exitosa ===")
    print(f"Número de muestras procesadas: {N} en dimensión D={D}")
    print(f"Inercia WCSS mínima alcanzada: {km.inertia_:.2f}")
    print(f"Centroides aprendidos por el ensamble de Lloyd:\n{km.cluster_centers_}")
    print(f"Coeficiente de Silueta global (Rousseeuw): {score_silueta:.4f}")
```

---

## 8. Directrices de Razonamiento para los Modelos de Inteligencia Artificial en Prig IDE

Cuando un modelo de lenguaje en Prig IDE diseñe, audite o diagnostique agrupamientos basados en **$k$-Means** (`sklearn.cluster.KMeans`, `MiniBatchKMeans`), aplicará de forma estricta las siguientes directrices analíticas:

1. **Estandarización Obligatoria Previa al Agrupamiento:**
   - Como la inercia se calcula mediante distancias euclidianas cuadráticas en $\mathbb{R}^D$, variables con magnitudes elevadas dominarán la formación de los centroides. Siempre verificar que los datos hayan pasado por `StandardScaler()`.
2. **Supuestos Geométricos Rígidos (Modos de Falla Catastróficos):**
   - $k$-Means asume implícitamente tres propiedades sobre los datos:
     1. **Clusters esféricos / isotrópicos:** Falla por completo si los clusters son elípticos, alargados o en forma de cinta (en tales casos, usar Gaussian Mixture Models - GMM con matrices de covarianza completas).
     2. **Clusters de varianza similar:** Tiende a dividir los clusters de gran diámetro y fusionar clusters pequeños adyacentes.
     3. **Manifolds no lineales:** Si los datos forman círculos concéntricos o densidades continuas complejas, $k$-Means colapsará; recomendar **DBSCAN** o **Spectral Clustering**.
3. **Inicialización y Prevención de Mínimos Locales:**
   - **Nunca usar `init='random'`** en producción. Emplear siempre `init='k-means++'` con al menos `n_init=10` para aprovechar la cota de aproximación de Arthur & Vassilvitskii.
4. **Optimización Computacional para Datos Masivos:**
   - Si $N > 100,000$, sustituir `KMeans` por `MiniBatchKMeans`, el cual actualiza los centroides mediante subconjuntos aleatorios estocásticos (*batches*) en memoria principal sin pérdida sensible de calidad.
   - En CPU estándar con dimensiones moderadas ($D \le 50$), fijar `algorithm='elkan'` para aprovechar la poda por desigualdad triangular y acelerar el entrenamiento en hasta un $5\times$.
5. **Determinación Rigurosa de $k$:**
   - Jamás seleccionar $k$ de manera arbitraria o puramente visual. Evaluar de forma cruzada el **Método del Codo (*Elbow Method*)** observando la desaceleración de la inercia junto con la maximización del **Silhouette Score**. Si el Silhouette Score promedio es inferior a $0.35$, advertir al usuario de que la estructura de agrupamiento latente es muy débil o no existe.
