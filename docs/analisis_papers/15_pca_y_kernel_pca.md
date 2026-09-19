# Monografía 15: PCA y Kernel PCA — Descomposición Espectral, SVD, Teorema de Eckart-Young y el Truco del Kernel en Espacios de Hilbert

> **Directorio de Ubicación:** `docs/analisis_papers/15_pca_y_kernel_pca.md`  
> **Ficha Técnica Modular Resumida:** [`docs/algoritmos_ml/15_pca_y_kernel_pca.md`](../algoritmos_ml/15_pca_y_kernel_pca.md)  
> **Estado del Documento:** Riguroso / Nivel Doctoral / Producción Académica  

---

## 1. Ficha Bibliográfica y Genealogía de Papers Seminales

1. **La Génesis Geométrica de los Ejes Principales (1901):**
   - **Título:** *On lines and planes of closest fit to systems of points in space*
   - **Autor:** Karl Pearson.
   - **Publicación:** *The London, Edinburgh, and Dublin Philosophical Magazine and Journal of Science*, Series 6, 2(11), pp. 559–572 (1901).
   - **Aporte Principal:** Primera formulación del problema geométrico de aproximación ortogonal: hallar rectas y planos hiperdimensionales que minimicen la suma de las distancias cuadradas ortogonales desde una nube de puntos observados. Demostró que la solución analítica correspondía a los ejes de inercia de la mecánica clásica.

2. **La Formalización Estadística de Componentes Principales (1933):**
   - **Título:** *Analysis of a complex of statistical variables into principal components*
   - **Autor:** Harold Hotelling (Columbia University).
   - **Publicación:** *Journal of Educational Psychology*, 24(6), pp. 417–441; 24(7), pp. 498–520 (1933).
   - **Aporte Principal:** Introducción del término canónico *Principal Components*. Derivación estricta desde la maximización sucesiva de la varianza muestral de combinaciones lineales no correlacionadas mediante multiplicadores de Lagrange, estableciendo el puente formal con la diagonalización de la matriz de covarianza.

3. **El Teorema de Aproximación Óptima de Bajo Rango (1936):**
   - **Título:** *The approximation of one matrix by another of lower rank*
   - **Autores:** Carl Eckart y Gale Young.
   - **Publicación:** *Psychometrika*, 1(3), pp. 211–218 (1936).
   - **Aporte Principal:** Demostración del **Teorema de Eckart-Young-Mirsky**, probando que la Descomposición en Valores Singulares (SVD) truncada a los $k$ valores singulares líderes proporciona la mejor aproximación determinista de rango $k$ para cualquier matriz bajo la norma de Frobenius y la norma espectral de operadores.

4. **El Algoritmo Numérico Estable de SVD (1965):**
   - **Título:** *Calculating the singular values and pseudo-inverse of a matrix*
   - **Autores:** Gene H. Golub y William Kahan.
   - **Publicación:** *Journal of the Society for Industrial and Applied Mathematics: Series B, Numerical Analysis*, 2(2), pp. 205–224 (1965).
   - **Aporte Principal:** Formulación del algoritmo Golub-Kahan (bidiagonalización de Householder seguida de iteraciones QR con desplazamientos implícitos) implementado en LINPACK/LAPACK (`dgesdd`), permitiendo calcular componentes principales directamente sobre la matriz de diseño $X$ sin requerir la formación de $X^T X$, preservando la precisión en coma flotante.

5. **La Extensión No Lineal: Kernel PCA (1998):**
   - **Título:** *Nonlinear Component Analysis as a Kernel Eigenvalue Problem*
   - **Autores:** Bernhard Schölkopf, Alexander Smola y Klaus-Robert Müller.
   - **Publicación:** *Neural Computation*, 10(5), pp. 1299–1319 (1998).
   - **Aporte Principal:** Generalización no lineal del PCA mapeando los datos de entrada a un Espacio de Hilbert con Núcleo Reproductor (RKHS) de dimensión potencialmente infinita $\mathcal{H}$. Demostración de que el problema de autovalores en $\mathcal{H}$ puede resolverse exactamente en tiempo polinomial mediante la diagonalización de la matriz de Gram centrada $\tilde{K} \in \mathbb{R}^{N \times N}$.

6. **Descomposición Probabilística Aleatoria para Big Data: Randomized SVD (2011):**
   - **Título:** *Finding Structure with Randomness: Probabilistic Algorithms for Constructing Approximate Matrix Decompositions*
   - **Autores:** Nathan Halko, Per-Gunnar Martinsson y Joel A. Tropp.
   - **Publicación:** *SIAM Review*, 53(2), pp. 217–288 (2011).
   - **Aporte Principal:** Algoritmos estocásticos que proyectan la matriz de datos sobre un subespacio aleatorio de dimensión $k + p$, reduciendo la complejidad computacional a $\mathcal{O}(N D \log k)$, permitiendo PCA en matrices con millones de filas y columnas en bibliotecas modernas como scikit-learn (`svd_solver='randomized'`).

---

## 2. Génesis Teórica: Dualidad Varianza Máxima vs. Error Mínimo de Reconstrucción

Sea un conjunto de datos $\mathcal{X} = \{x_1, x_2, \dots, x_N\} \subset \mathbb{R}^D$ estructurado en una matriz de diseño $X \in \mathbb{R}^{N \times D}$.  
Asumimos inicialmente que los datos han sido **estrictamente centrados en la media**:
$$\mu = \frac{1}{N} \sum_{i=1}^N x_i = \mathbf{0}, \quad X_c = X - \mathbf{1}_N \mu^T$$

El Análisis de Componentes Principales (PCA) emerge de dos perspectivas geométricas equivalentes:

```
                  ┌─────────────────────────────────────────────────────────┐
                  │              Perspectiva 1: Hotelling (1933)             │
                  │        Maximización de la Varianza Proyectada           │
                  └───────────────────────────┬─────────────────────────────┘
                                              │
                                              ▼ (Equivalencia Demostrada)
                                              │
                  ┌───────────────────────────┴─────────────────────────────┐
                  │               Perspectiva 2: Pearson (1901)              │
                  │    Minimización del Error Cuadrático de Reconstrucción  │
                  └─────────────────────────────────────────────────────────┘
```

### 2.1. Perspectiva 1: Maximización de la Varianza Proyectada (Hotelling)
Deseamos encontrar una dirección ortogonal unitaria $v_1 \in \mathbb{R}^D$ con $\|v_1\|_2 = 1$ sobre la cual la proyección de los datos $z_i^{(1)} = x_i^T v_1$ tenga la máxima dispersión muestral posible:
$$\text{Var}(z^{(1)}) = \frac{1}{N-1} \sum_{i=1}^N (x_i^T v_1 - 0)^2 = \frac{1}{N-1} v_1^T \left( \sum_{i=1}^N x_i x_i^T \right) v_1 = v_1^T \Sigma v_1$$
donde $\Sigma = \frac{1}{N-1} X_c^T X_c \in \mathbb{R}^{D \times D}$ es la **matriz de covarianza muestral insesgada**.

### 2.2. Perspectiva 2: Minimización del Error de Reconstrucción (Pearson)
Alternativamente, buscamos un subespacio lineal de dimensión $k < D$ definido por una base ortonormal $\{v_1, \dots, v_k\}$ tal que al proyectar cada muestra $x_i$ sobre dicho subespacio, la distancia euclidiana ortogonal de reconstrucción sea mínima:
$$\min_{\{v_j\}_{j=1}^k} \frac{1}{N} \sum_{i=1}^N \left\| x_i - \sum_{j=1}^k (x_i^T v_j) v_j \right\|_2^2, \quad \text{sujeto a } v_j^T v_l = \delta_{jl}$$

### 2.3. Demostración de la Equivalencia entre Ambas Perspectivas
Por el teorema de Pitágoras en espacios euclidianos, descomponemos la norma al cuadrado del vector original $x_i$ en su componente en el subespacio proyectado y su componente ortogonal residual:
$$\|x_i\|_2^2 = \left\| \sum_{j=1}^k (x_i^T v_j) v_j \right\|_2^2 + \left\| x_i - \sum_{j=1}^k (x_i^T v_j) v_j \right\|_2^2 = \sum_{j=1}^k (x_i^T v_j)^2 + \text{Error}_i^2$$
Promediando sobre las $N$ muestras:
$$\frac{1}{N} \sum_{i=1}^N \|x_i\|_2^2 = \sum_{j=1}^k \left[ \frac{1}{N} \sum_{i=1}^N (x_i^T v_j)^2 \right] + \frac{1}{N} \sum_{i=1}^N \text{Error}_i^2$$
Dado que el término del lado izquierdo $\frac{1}{N} \sum_{i=1}^N \|x_i\|_2^2 = \text{Tr}(\Sigma)$ es una constante intrínseca fija e invariante del dataset:
$$\text{Minimizar } \frac{1}{N} \sum_{i=1}^N \text{Error}_i^2 \iff \text{Maximizar } \sum_{j=1}^k v_j^T \Sigma v_j$$
**Conclusión Fundamental:** Hallar el subespacio que minimiza la distorsión de compresión es estrictamente idéntico a hallar el subespacio que captura la mayor varianza posible de los datos.

### 2.4. La Necesidad Imperativa del Centrado en la Media
Si no se resta el vector de medias $\mu$, la matriz $X^T X$ pasa a calcular momentos no centrados de segundo orden:
$$\frac{1}{N} X^T X = \Sigma + \mu \mu^T$$
Si $\|\mu\|_2 \gg 0$, el término $\mu \mu^T$ tendrá un autovalor dominante de magnitud aproximada $N \|\mu\|_2^2$ cuyo autovector apuntará directamente hacia el centro de gravedad de la distribución $\mu$. En consecuencia:
- El primer componente principal **no capturará la dispersión de los datos**, sino la distancia del origen al centroide.
- Las componentes subsecuentes se verán forzadas a ser ortogonales a la media, sesgando por completo toda la estructura topológica latente.

---

## 3. Derivaciones Matemáticas Paso a Paso

### 3.1. Formulación Variacional con Multiplicadores de Lagrange

Deseamos maximizar la varianza sobre el primer eje unitario $v_1$:
$$\max_{v_1} v_1^T \Sigma v_1 \quad \text{sujeto a} \quad v_1^T v_1 = 1$$

Construimos la función Lagrangiana $\mathcal{L}(v_1, \lambda_1)$:
$$\mathcal{L}(v_1, \lambda_1) = v_1^T \Sigma v_1 - \lambda_1 (v_1^T v_1 - 1)$$

Calculamos la derivada respecto al vector $v_1$ utilizando identidades de cálculo matricial ($\frac{\partial (x^T A x)}{\partial x} = 2 A x$ para $A$ simétrica):
$$\frac{\partial \mathcal{L}}{\partial v_1} = 2 \Sigma v_1 - 2 \lambda_1 v_1 = \mathbf{0} \implies \Sigma v_1 = \lambda_1 v_1$$

**Deducciones Clave:**
1. El vector $v_1$ debe ser obligatoriamente un **autovector** (*eigenvector*) de la matriz de covarianza $\Sigma$.
2. Premultiplicando la ecuación por $v_1^T$:
   $$v_1^T \Sigma v_1 = \lambda_1 v_1^T v_1 = \lambda_1 (1) = \lambda_1$$
3. La varianza proyectada es exactamente igual al **autovalor** $\lambda_1$. Por lo tanto, para maximizar la varianza, debemos elegir el autovector asociado al **mayor autovalor** $\lambda_{\max}(\Sigma)$.

#### Componentes Principales Subsecuentes
Para el segundo componente $v_2$, imponemos ortogonalidad con $v_1$ ($v_2^T v_1 = 0$) y norma unitaria ($v_2^T v_2 = 1$):
$$\mathcal{L}(v_2, \lambda_2, \phi) = v_2^T \Sigma v_2 - \lambda_2 (v_2^T v_2 - 1) - \phi (v_2^T v_1)$$
Derivando e igualando a cero:
$$2 \Sigma v_2 - 2 \lambda_2 v_2 - \phi v_1 = \mathbf{0}$$
Premultiplicando por $v_1^T$:
$$2 v_1^T \Sigma v_2 - 2 \lambda_2 (v_1^T v_2) - \phi (v_1^T v_1) = 0$$
Dado que $\Sigma$ es simétrica: $v_1^T \Sigma = (\Sigma v_1)^T = (\lambda_1 v_1)^T = \lambda_1 v_1^T$.  
Sustituyendo y recordando que $v_1^T v_2 = 0$ y $v_1^T v_1 = 1$:
$$2 \lambda_1 (v_1^T v_2) - 0 - \phi (1) = 0 \implies \phi = 0$$
La ecuación colapsa nuevamente al problema de autovalores estándar:
$$\Sigma v_2 = \lambda_2 v_2$$
Así, $v_2$ es el autovector correspondiente al **segundo mayor autovalor** $\lambda_2 \le \lambda_1$.  
Por inducción sobre $k = 1, \dots, D$, las direcciones principales son la base ortonormal de autovectores ordenada de forma decreciente según sus autovalores $\lambda_1 \ge \lambda_2 \ge \dots \ge \lambda_D \ge 0$.

---

### 3.2. El Teorema de Eckart-Young-Mirsky (1936)

Consideremos la matriz centrada $X \in \mathbb{R}^{N \times D}$.  
Deseamos encontrar la matriz de rango $k < \text{rango}(X)$, denominada $X_k$, que resuelva:
$$\min_{\text{rango}(A) \le k} \|X - A\|_F^2$$
donde $\|M\|_F = \sqrt{\sum_{i,j} M_{ij}^2} = \sqrt{\text{Tr}(M^T M)}$ es la norma de Frobenius.

#### Teorema:
Sea la Descomposición en Valores Singulares (SVD) de $X$:
$$X = U S V^T = \sum_{j=1}^r s_j u_j v_j^T, \quad s_1 \ge s_2 \ge \dots \ge s_r > 0$$
donde $U \in \mathbb{R}^{N \times N}$ y $V \in \mathbb{R}^{D \times D}$ son matrices ortogonales, y $S \in \mathbb{R}^{N \times D}$ contiene los valores singulares $s_j \ge 0$ en su diagonal.  
Entonces, la matriz óptima $X_k$ es la **SVD truncada**:
$$X_k = U_k S_k V_k^T = \sum_{j=1}^k s_j u_j v_j^T$$
y el error residual de reconstrucción es exactamente la suma de los valores singulares descartados al cuadrado:
$$\min_{\text{rango}(A) \le k} \|X - A\|_F^2 = \|X - X_k\|_F^2 = \sum_{j=k+1}^r s_j^2$$
Bajo la norma espectral de operadores $\|M\|_2 = \max_{\|x\|=1} \|M x\|_2$, el error es exactamente el primer valor singular descartado:
$$\min_{\text{rango}(A) \le k} \|X - A\|_2 = s_{k+1}$$

---

### 3.3. Dualidad Matemática: Covarianza vs. SVD Directa

Existe una relación analítica exacta entre la diagonalización de la covarianza muestral $\Sigma$ y la descomposición SVD de la matriz centrada $X$:
$$\Sigma = \frac{1}{N-1} X^T X = \frac{1}{N-1} (U S V^T)^T (U S V^T) = \frac{1}{N-1} V S^T (U^T U) S V^T$$
Como $U$ es ortogonal ($U^T U = I_N$):
$$\Sigma = V \left( \frac{S^2}{N-1} \right) V^T = V \Lambda V^T$$
donde $\Lambda = \text{diag}(\lambda_1, \dots, \lambda_D)$ es la matriz diagonal de autovalores.

**Relaciones de Identidad:**
1. Los autovectores $v_j$ de $\Sigma$ son idénticos a los **vectores singulares derechos** (columnas de $V$).
2. Los autovalores $\lambda_j$ se obtienen directamente de los valores singulares $s_j$:
   $$\lambda_j = \frac{s_j^2}{N-1}$$
3. Las coordenadas latentes proyectadas $Z \in \mathbb{R}^{N \times k}$ se calculan directamente sin multiplicar por $X$:
   $$Z = X V_k = (U S V^T) V_k = U_k S_k$$

#### ¿Por qué SVD es Numéricamente Superior a Calcular $\Sigma$?
En aritmética de punto flotante IEEE 754 (precisión doble de 64 bits con ~16 dígitos decimales significativos):
1. **Número de Condición:**  
   Sea $\kappa(X) = \frac{s_{\max}(X)}{s_{\min}(X)}$ el número de condición de $X$.  
   Al calcular explícitamente el producto matricial $X^T X$, el número de condición se eleva al cuadrado:
   $$\kappa(X^T X) = \kappa(X)^2$$
   Si $\kappa(X) = 10^9$, $X$ es invertible en doble precisión. Sin embargo, $\kappa(X^T X) = 10^{18} > 10^{16}$, provocando que $X^T X$ sea computacionalmente singular y pierda todos sus dígitos de precisión en autovalores pequeños.
2. **Complejidad Asintótica:**  
   - Formar $\Sigma = \frac{1}{N-1} X^T X$ cuesta $\mathcal{O}(N D^2)$, y su diagonalización $\mathcal{O}(D^3)$. Si $N \ll D$, esto es catastróficamente ineficiente.
   - SVD directa requiere $\mathcal{O}(N D \min(N, D))$, adaptándose automáticamente a regímenes $N \gg D$ o $D \gg N$.

---

### 3.4. Varianza Explicada y Blanqueamiento (*Whitening*)

#### Razón de Varianza Explicada (Explained Variance Ratio - EVR)
La varianza total del sistema es la traza de la covarianza:
$$\text{Var}_{\text{total}} = \text{Tr}(\Sigma) = \sum_{j=1}^D \lambda_j = \frac{1}{N-1} \sum_{j=1}^{\min(N,D)} s_j^2$$
La proporción de información preservada por los primeros $k$ componentes es:
$$\text{EVR}_k = \frac{\sum_{j=1}^k \lambda_j}{\sum_{i=1}^D \lambda_i} = \frac{\sum_{j=1}^k s_j^2}{\sum_{i=1}^D s_i^2}$$

#### Transformación de Blanqueamiento (*Whitening*)
Para algoritmos aguas abajo sensibles a escalas (como redes neuronales o estimadores de densidad por kernels), se normaliza la proyección para que la covarianza resultante sea exactamente la matriz identidad $I_k$:
$$Z_{\text{white}} = Z \Lambda_k^{-1/2} = X V_k \Lambda_k^{-1/2} = U_k \sqrt{N-1}$$
Demostración de covarianza identidad:
$$\text{Cov}(Z_{\text{white}}) = \frac{1}{N-1} Z_{\text{white}}^T Z_{\text{white}} = \frac{1}{N-1} (\sqrt{N-1} U_k^T) (U_k \sqrt{N-1}) = U_k^T U_k = I_k$$
El blanqueamiento elimina por completo las correlaciones lineales de segundo orden y homogeniza las escalas a varianza unitaria.

---

### 3.5. Derivación Completa de Kernel PCA (Schölkopf, Smola & Müller, 1998)

Cuando la variedad (*manifold*) de los datos es no lineal (por ejemplo, espirales entrelazadas o esferas concéntricas), PCA lineal falla al proyectar todas las estructuras sobre un hiperplano rígido.  
**Kernel PCA** mapea los datos a un espacio de Hilbert de características $\mathcal{H}$ mediante una función no lineal:
$$\Phi: \mathbb{R}^D \to \mathcal{H}, \quad x_i \mapsto \Phi(x_i)$$
donde la dimensión de $\mathcal{H}$ puede ser infinita.

Asumamos temporalmente que los datos en $\mathcal{H}$ están centrados: $\sum_{i=1}^N \Phi(x_i) = \mathbf{0}$.  
La matriz de covarianza en $\mathcal{H}$ (un operador lineal continuo) es:
$$C = \frac{1}{N} \sum_{i=1}^N \Phi(x_i) \Phi(x_i)^T$$
Deseamos resolver la ecuación de autovalores $C v = \lambda v$ para autovectores $v \in \mathcal{H}$ con $\lambda > 0$:
$$\frac{1}{N} \sum_{i=1}^N \Phi(x_i) \left( \Phi(x_i)^T v \right) = \lambda v \implies v = \frac{1}{N \lambda} \sum_{i=1}^N \langle \Phi(x_i), v \rangle_{\mathcal{H}} \Phi(x_i)$$

**El Lema del Subespacio Generado:**  
Todo autovector $v$ correspondiente a $\lambda > 0$ reside obligatoriamente en el subespacio generado (*span*) por los vectores de entrenamiento transformados $\{\Phi(x_1), \dots, \Phi(x_N)\}$.  
Por lo tanto, existen coeficientes $\boldsymbol{\alpha} = (\alpha_1, \dots, \alpha_N)^T \in \mathbb{R}^N$ tales que:
$$v = \sum_{i=1}^N \alpha_i \Phi(x_i)$$

Sustituyendo esta expansión en la ecuación de autovalores:
$$\frac{1}{N} \sum_{i=1}^N \Phi(x_i) \Phi(x_i)^T \left( \sum_{j=1}^N \alpha_j \Phi(x_j) \right) = \lambda \sum_{i=1}^N \alpha_i \Phi(x_i)$$
Multiplicando escalarmente ambos lados por $\Phi(x_k)^T$ para todo $k = 1, \dots, N$:
$$\frac{1}{N} \sum_{i=1}^N \langle \Phi(x_k), \Phi(x_i) \rangle \sum_{j=1}^N \alpha_j \langle \Phi(x_i), \Phi(x_j) \rangle = \lambda \sum_{i=1}^N \alpha_i \langle \Phi(x_k), \Phi(x_i) \rangle$$

Definiendo la **matriz de Kernel de Gram** $K \in \mathbb{R}^{N \times N}$ con $K_{ij} = k(x_i, x_j) = \langle \Phi(x_i), \Phi(x_j) \rangle_{\mathcal{H}}$:
$$\frac{1}{N} K^2 \boldsymbol{\alpha} = \lambda K \boldsymbol{\alpha} \iff K (K \boldsymbol{\alpha} - N \lambda \boldsymbol{\alpha}) = \mathbf{0}$$
Para encontrar las direcciones principales no triviales en $\mathcal{H}$, basta con resolver el **problema de autovalores matricial estándar sobre la matriz de Gram**:
$$K \boldsymbol{\alpha} = \tilde{\lambda} \boldsymbol{\alpha}, \quad \text{donde } \tilde{\lambda} = N \lambda$$

#### Condición de Normalización de Autovectores en $\mathcal{H}$
El autovector $v$ debe ser unitario en $\mathcal{H}$: $\langle v, v \rangle = 1$.  
Expandiendo:
$$1 = \left\langle \sum_{i=1}^N \alpha_i \Phi(x_i), \sum_{j=1}^N \alpha_j \Phi(x_j) \right\rangle = \sum_{i=1}^N \sum_{j=1}^N \alpha_i \alpha_j K_{ij} = \boldsymbol{\alpha}^T K \boldsymbol{\alpha}$$
Como $K \boldsymbol{\alpha} = \tilde{\lambda} \boldsymbol{\alpha}$:
$$1 = \boldsymbol{\alpha}^T (\tilde{\lambda} \boldsymbol{\alpha}) = \tilde{\lambda} \|\boldsymbol{\alpha}\|_2^2 \implies \|\boldsymbol{\alpha}\|_2 = \frac{1}{\sqrt{\tilde{\lambda}}} = \frac{1}{\sqrt{N \lambda}}$$
Por ende, tras calcular el autovector euclidiano normalizado $\boldsymbol{\alpha}_{\text{unit}}$ con $\|\boldsymbol{\alpha}_{\text{unit}}\|_2 = 1$, debemos reescalarlo:
$$\boldsymbol{\alpha}^k = \frac{1}{\sqrt{\tilde{\lambda}_k}} \boldsymbol{\alpha}_{\text{unit}}^k$$

#### Centrado Riguroso en el Espacio de Hilbert sin Evaluar $\Phi$
En la práctica, los vectores $\Phi(x_i)$ casi nunca tienen media cero en $\mathcal{H}$.  
Definimos los puntos centrados en el espacio de características:
$$\tilde{\Phi}(x_i) = \Phi(x_i) - \frac{1}{N} \sum_{j=1}^N \Phi(x_j)$$
El elemento de la matriz de Kernel centrada es:
$$\tilde{K}_{ij} = \langle \tilde{\Phi}(x_i), \tilde{\Phi}(x_j) \rangle = \left\langle \Phi(x_i) - \frac{1}{N}\sum_m \Phi(x_m), \Phi(x_j) - \frac{1}{N}\sum_l \Phi(x_l) \right\rangle$$
Expandiendo el producto interno:
$$\tilde{K}_{ij} = K_{ij} - \frac{1}{N} \sum_{l=1}^N K_{il} - \frac{1}{N} \sum_{m=1}^N K_{mj} + \frac{1}{N^2} \sum_{m=1}^N \sum_{l=1}^N K_{ml}$$
Expresado en álgebra matricial compacta:
$$\tilde{K} = K - \mathbf{1}_N K - K \mathbf{1}_N + \mathbf{1}_N K \mathbf{1}_N$$
donde $\mathbf{1}_N \in \mathbb{R}^{N \times N}$ es la matriz cuyas entradas son todas iguales a $\frac{1}{N}$ ($\mathbf{1}_N = \frac{1}{N} \mathbf{e} \mathbf{e}^T$).

#### Proyección de un Nuevo Punto de Prueba $x_* \in \mathbb{R}^D$
Para proyectar un punto fuera de muestra $x_*$ sobre el $k$-ésimo componente principal $v_k$:
$$y_k(x_*) = \langle v_k, \tilde{\Phi}(x_*) \rangle = \sum_{i=1}^N \alpha_i^k \langle \tilde{\Phi}(x_i), \tilde{\Phi}(x_*) \rangle = \sum_{i=1}^N \alpha_i^k \tilde{k}(x_i, x_*)$$
donde el vector de kernel centrado entre el nuevo punto y el dataset de entrenamiento se calcula evaluando:
$$\tilde{k}(x_i, x_*) = k(x_i, x_*) - \frac{1}{N} \sum_{j=1}^N k(x_j, x_*) - \frac{1}{N} \sum_{m=1}^N k(x_i, x_m) + \frac{1}{N^2} \sum_{m=1}^N \sum_{j=1}^N k(x_m, x_j)$$

---

## 4. Arquitectura de Sistemas y Algoritmos de Descomposición

```
                                 ┌─────────────────────────┐
                                 │   Dataset Centrado X    │
                                 └────────────┬────────────┘
                                              │
                      ┌───────────────────────┴───────────────────────┐
                      ▼                                               ▼
         ┌─────────────────────────┐                     ┌─────────────────────────┐
         │  Régimen Lineal (PCA)   │                     │  Régimen No Lineal      │
         └────────────┬────────────┘                     │      (Kernel PCA)       │
                      │                                  └────────────┬────────────┘
         ┌────────────┴────────────┐                                  │
         ▼                         ▼                                  ▼
┌─────────────────┐       ┌─────────────────┐            ┌─────────────────────────┐
│  LAPACK dgesdd  │       │ Randomized SVD  │            │ Matriz de Gram K (N×N)  │
│ Exacto O(ND·min)│       │ Halko et al.    │            │ Centrado K̃              │
│ Memoria: O(ND)  │       │ O(ND·log k)     │            │ Descomposición O(N³)    │
└─────────────────┘       └─────────────────┘            └─────────────────────────┘
```

### 4.1. Taxonomía de Motores de Resolución Numérica

1. **Exacto (LAPACK `dgesdd` - Divide and Conquer SVD):**
   - Calcula todos los valores singulares y autovectores con precisión de máquina.
   - Complejidad temporal: $\mathcal{O}(N D \min(N, D))$.
   - Ideal para $D \le 10,000$ y $N \le 50,000$.

2. **Randomized SVD (Halko, Martinsson & Tropp, 2011):**
   - Extrae una matriz gaussiana aleatoria $\Omega \in \mathbb{R}^{D \times (k + p)}$, donde $p \approx 10$ es el margen de sobremuestreo (*oversampling*).
   - Forma el esbozo $Y = X \Omega \in \mathbb{R}^{N \times (k+p)}$ y calcula su base ortonormal $Q$ mediante factorización QR: $Y = Q R$.
   - Proyecta la matriz original sobre el subespacio reducido: $B = Q^T X \in \mathbb{R}^{(k+p) \times D}$.
   - Calcula la SVD pequeña de $B$: $B = \tilde{U} S V^T$, recuperando $U = Q \tilde{U}$.
   - Complejidad: $\mathcal{O}(N D (k + p))$, reduciendo drásticamente el tiempo de cómputo en grandes volúmenes de datos.

3. **Incremental PCA (Ross et al., 2008):**
   - Procesa los datos por mini-lotes secuenciales (*chunks*) que no caben en memoria RAM.
   - Aplica actualizaciones de bajo rango a la descomposición SVD existente mediante rotaciones de Givens o SVD combinada $\text{SVD}([U_k S_k, X_{\text{batch}}])$, manteniendo memoria constante $\mathcal{O}(\text{batch\_size} \times k)$.

4. **Sparse PCA (Zou, Hastie & Tibshirani, 2006):**
   - Modula el problema imponiendo una penalización Lasso $\ell_1$ sobre las cargas de los autovectores $V$.
   - Produce coeficientes exactamente iguales a cero, permitiendo interpretar cada componente principal como una combinación de un número reducido y legible de variables físicas originales.

---

## 5. Tabla Comparativa y Criterios de Selección

| Dimensión de Análisis | PCA Clásico (Pearson / Hotelling) | Kernel PCA (Schölkopf et al.) | Autoencoder Neuronal (Rumelhart) |
|---|---|---|---|
| **Naturaleza del Mapeo** | Proyección ortogonal estrictamente lineal | Proyección no lineal vía RKHS | No lineal arbitrario parametrizado |
| **Garantía de Óptimo** | Óptimo global analítico único (Eckart-Young) | Óptimo global en $\mathcal{H}$ (convexo) | Mínimos locales (descenso por gradiente) |
| **Complejidad de Entrenamiento** | $\mathcal{O}(N D \min(N, D))$ con SVD | $\mathcal{O}(N^3)$ por diagonalización de Gram | $\mathcal{O}(\text{epochs} \cdot N \cdot |\Theta|)$ |
| **Consumo de Memoria** | $\mathcal{O}(N D)$ | $\mathcal{O}(N^2)$ (almacenamiento de $K$) | $\mathcal{O}(\text{batch\_size} \cdot D + |\Theta|)$ |
| **Inferencia Fuera de Muestra** | Directa: $z_* = x_* V_k$ ($\mathcal{O}(D k)$) | Requiere evaluar $N$ kernels ($\mathcal{O}(N D)$) | Inferencia hacia adelante rápida ($\mathcal{O}(|\Theta|)$) |
| **Reconstrucción Inversa** | Exacta y cerrada: $\hat{x} = z V_k^T + \mu$ | Difícil (Problema del *Pre-Image*) | Inmediata mediante red decodificadora |
| **Escalabilidad ante Muestras $N$** | Excelente ($N > 10^7$ con Randomized) | Mala ($N > 50,000$ requiere Nyström) | Excelente (Entrenamiento por mini-lotes) |

### 5.1. Reglas de Selección de Componentes $k$

1. **Criterio de Varianza Acumulada:** Retener el menor $k$ tal que $\text{EVR}_k \ge 0.95$ (95% de varianza explicada) o $0.99$.
2. **Criterio de Kaiser-Guttman (1960):** En matrices estandarizadas con varianza unitaria por columna ($\lambda_{\text{promedio}} = 1$), retener únicamente componentes con autovalores $\lambda_j \ge 1.0$.
3. **Criterio del Gráfico de Sedimentación (*Scree Plot* / Cattell, 1966):** Graficar $\lambda_j$ en orden decreciente e identificar el punto de inflexión ("codo"), donde la pendiente pasa de abrupta a meseta asintótica gobernada por ruido blanco.

---

## 6. Implementación Pura en Python y NumPy (Sin Librerías de ML)

A continuación se presenta la implementación de nivel de producción de **PCA** y **Kernel PCA**, prescindiendo de `scikit-learn` o librerías de alto nivel, utilizando únicamente `numpy` para operaciones de álgebra lineal canónicas.

```python
import numpy as np


class PCA_Puro:
    """
    Implementación rigurosa de Análisis de Componentes Principales (PCA).
    Utiliza Descomposición en Valores Singulares (SVD) directa sobre la matriz centrada
    para garantizar máxima estabilidad numérica y prevenir la pérdida de precisión
    inherente al cálculo explícito de X^T X.
    """
    def __init__(self, n_components=None, whiten=False):
        self.n_components = n_components
        self.whiten = whiten
        self.mean_ = None
        self.components_ = None          # Autovectores unitarios V_k^T (shape: [k, D])
        self.singular_values_ = None     # Valores singulares s_j (shape: [k])
        self.explained_variance_ = None  # Autovalores lambda_j (shape: [k])
        self.explained_variance_ratio_ = None

    def fit(self, X):
        """Ajusta el modelo PCA calculando la media y los ejes principales ortogonales."""
        N, D = X.shape
        # 1. Centrado estricto de las muestras
        self.mean_ = np.mean(X, axis=0)
        X_centrado = X - self.mean_

        # 2. Descomposición SVD directa: X_c = U S V^T
        # full_matrices=False calcula la SVD reducida: U shape (N, min(N,D)), S shape (min(N,D)), Vt shape (min(N,D), D)
        U, S, Vt = np.linalg.svd(X_centrado, full_matrices=False)

        # 3. Cálculo de autovalores de covarianza: lambda_j = s_j^2 / (N - 1)
        varianza_total = np.sum(S**2) / (N - 1)
        autovalores = (S**2) / (N - 1)

        # 4. Selección del número de componentes k
        if self.n_components is None:
            k = min(N, D)
        elif isinstance(self.n_components, float) and 0.0 < self.n_components < 1.0:
            # Seleccionar por umbral de varianza acumulada
            ratio_acumulado = np.cumsum(autovalores) / np.sum(autovalores)
            k = int(np.searchsorted(ratio_acumulado, self.n_components)) + 1
        else:
            k = int(self.n_components)

        k = min(k, min(N, D))

        # Almacenamiento de atributos de proyección
        self.components_ = Vt[:k]  # Filas corresponden a autovectores directores v_j^T
        self.singular_values_ = S[:k]
        self.explained_variance_ = autovalores[:k]
        self.explained_variance_ratio_ = autovalores[:k] / varianza_total

        return self

    def transform(self, X):
        """Proyecta las muestras sobre el subespacio latente ortogonal Z = X_c · V_k."""
        X_centrado = X - self.mean_
        # components_.T tiene dimensión (D, k)
        Z = np.dot(X_centrado, self.components_.T)

        if self.whiten:
            # Dividir por la desviación estándar muestral proyectada: sqrt(lambda_j)
            desv_estandar = np.sqrt(self.explained_variance_)
            Z /= (desv_estandar + 1e-12)

        return Z

    def fit_transform(self, X):
        """Ajusta el modelo y proyecta los datos de entrenamiento."""
        return self.fit(X).transform(X)

    def inverse_transform(self, Z):
        """Reconstruye los datos originales desde las coordenadas latentes: X_hat = Z · V_k + mu."""
        if self.whiten:
            Z = Z * np.sqrt(self.explained_variance_)
        return np.dot(Z, self.components_) + self.mean_


class KernelPCA_Puro:
    """
    Implementación rigurosa de Kernel PCA (Schölkopf, Smola & Müller 1998).
    Resuelve el problema de autovalores sobre la matriz de Gram centrada K_tilde
    en un Espacio de Hilbert Reproductor (RKHS).
    """
    def __init__(self, n_components=2, kernel='rbf', gamma=None, degree=3, coef0=1.0):
        self.n_components = n_components
        self.kernel = kernel
        self.gamma = gamma
        self.degree = degree
        self.coef0 = coef0
        self.X_fit_ = None
        self.alphas_ = None         # Autovectores normalizados en Hilbert (shape: [N, k])
        self.lambdas_ = None        # Autovalores del operador de Kernel
        self.K_fit_rows_mean_ = None
        self.K_fit_all_mean_ = None

    def _calcular_matriz_kernel(self, X1, X2):
        """Calcula la matriz de similitud de Gram K(X1, X2)."""
        if self.kernel == 'linear':
            return np.dot(X1, X2.T)
        elif self.kernel == 'rbf':
            gamma = self.gamma if self.gamma is not None else 1.0 / X1.shape[1]
            # Cálculo vectorizado de distancias euclidianas al cuadrado: ||x - y||^2 = ||x||^2 + ||y||^2 - 2 x y^T
            dist_sq = (np.sum(X1**2, axis=1, keepdims=True) + 
                       np.sum(X2**2, axis=1, keepdims=True).T - 
                       2.0 * np.dot(X1, X2.T))
            return np.exp(-gamma * np.maximum(dist_sq, 0.0))
        elif self.kernel == 'poly':
            gamma = self.gamma if self.gamma is not None else 1.0 / X1.shape[1]
            return (gamma * np.dot(X1, X2.T) + self.coef0)**self.degree
        else:
            raise ValueError(f"Kernel no soportado: {self.kernel}")

    def fit(self, X):
        """Ajusta Kernel PCA calculando y diagonalizando la matriz de Gram centrada."""
        N = X.shape[0]
        self.X_fit_ = X.copy()

        # 1. Matriz de Kernel original K
        K = self._calcular_matriz_kernel(X, X)

        # 2. Centrado riguroso en el espacio de características:
        # K_tilde = K - 1_N K - K 1_N + 1_N K 1_N
        self.K_fit_rows_mean_ = np.mean(K, axis=0, keepdims=True)  # Shape (1, N)
        self.K_fit_all_mean_ = np.mean(K)                          # Escalar

        K_tilde = K - self.K_fit_rows_mean_ - np.mean(K, axis=1, keepdims=True) + self.K_fit_all_mean_

        # 3. Descomposición espectral de matriz simétrica: eigh
        autovalores, autovectores = np.linalg.eigh(K_tilde)

        # 4. Ordenar de mayor a menor autovalor
        indices_ordenados = np.argsort(autovalores)[::-1]
        autovalores = autovalores[indices_ordenados]
        autovectores = autovectores[:, indices_ordenados]

        # 5. Filtrar autovalores estrictamente positivos (evitar artefactos numéricos negativos)
        mascara_positiva = autovalores > 1e-10
        autovalores = autovalores[mascara_positiva]
        autovectores = autovectores[:, mascara_positiva]

        k = min(self.n_components, len(autovalores))
        self.lambdas_ = autovalores[:k]
        
        # 6. Normalización rigurosa de autovectores en el espacio de Hilbert:
        # ||v_k||_H = 1  =>  alpha_k = v_k / sqrt(lambda_k)
        self.alphas_ = autovectores[:, :k] / np.sqrt(self.lambdas_)

        return self

    def transform(self, X):
        """Proyecta nuevas muestras mediante el producto interno evaluado por el kernel."""
        # 1. Kernel cruzado entre muestras nuevas X y muestras de entrenamiento X_fit_
        K_cross = self._calcular_matriz_kernel(X, self.X_fit_)  # Shape (N_new, N_fit)

        # 2. Centrado de la matriz de Kernel cruzada
        K_cross_rows_mean = np.mean(K_cross, axis=1, keepdims=True)  # Shape (N_new, 1)
        K_cross_tilde = K_cross - self.K_fit_rows_mean_ - K_cross_rows_mean + self.K_fit_all_mean_

        # 3. Proyección latente: Y = K_tilde_cross · alphas
        return np.dot(K_cross_tilde, self.alphas_)

    def fit_transform(self, X):
        """Ajusta y retorna la proyección sobre las componentes de Kernel de entrenamiento."""
        self.fit(X)
        # Para datos de entrenamiento, K_tilde · alpha_k = lambda_k · alpha_k = v_unit_k * sqrt(lambda_k)
        return self.transform(X)


# =====================================================================
# Verificación Numérica: Comparación de Separabilidad Lineal vs. No Lineal
# =====================================================================
if __name__ == "__main__":
    np.random.seed(42)

    # -----------------------------------------------------------------
    # Test 1: PCA Lineal en Distribución Gaussiana Anisotrópica
    # -----------------------------------------------------------------
    N = 300
    # Generar elipse 2D rotada
    X_original = np.random.randn(N, 2)
    matriz_rotacion = np.array([[np.cos(np.pi/4), -np.sin(np.pi/4)],
                                [np.sin(np.pi/4),  np.cos(np.pi/4)]])
    X_lineal = np.dot(X_original * np.array([5.0, 1.0]), matriz_rotacion) + np.array([10.0, -5.0])

    pca = PCA_Puro(n_components=2, whiten=False)
    Z_pca = pca.fit_transform(X_lineal)
    X_rec = pca.inverse_transform(Z_pca)

    error_reconstruccion = np.mean((X_lineal - X_rec)**2)

    print("=== Validación 1: PCA Lineal (SVD Directa) ===")
    print(f"Media aprendida: {pca.mean_}")
    print(f"Razón de varianza explicada (EVR): {pca.explained_variance_ratio_}")
    print(f"Varianza total explicada: {np.sum(pca.explained_variance_ratio_)*100:.2f}%")
    print(f"Error cuadrático medio de reconstrucción (debe ser ~0.0): {error_reconstruccion:.2e}")
    print(f"Ortogonalidad de componentes (|v1 . v2|): {abs(np.dot(pca.components_[0], pca.components_[1])):.2e}\n")

    # -----------------------------------------------------------------
    # Test 2: Kernel PCA en Círculos Concéntricos (No Separables Linealmente)
    # -----------------------------------------------------------------
    n_muestras = 150
    # Círculo interior
    r_in = 1.0 + 0.1 * np.random.randn(n_muestras)
    theta_in = np.random.uniform(0, 2 * np.pi, n_muestras)
    X_in = np.stack([r_in * np.cos(theta_in), r_in * np.sin(theta_in)], axis=1)

    # Círculo exterior
    r_out = 4.0 + 0.1 * np.random.randn(n_muestras)
    theta_out = np.random.uniform(0, 2 * np.pi, n_muestras)
    X_out = np.stack([r_out * np.cos(theta_out), r_out * np.sin(theta_out)], axis=1)

    X_circulos = np.vstack([X_in, X_out])
    y_circulos = np.hstack([np.zeros(n_muestras), np.ones(n_muestras)])

    # PCA Lineal falla en separar círculos concéntricos
    pca_circ = PCA_Puro(n_components=2)
    Z_pca_circ = pca_circ.fit_transform(X_circulos)

    # Kernel PCA con RBF kernel desenrolla la variedad no lineal
    kpca = KernelPCA_Puro(n_components=2, kernel='rbf', gamma=0.5)
    Z_kpca = kpca.fit_transform(X_circulos)

    # Medir separación en el primer componente latente
    # Diferencia de medias normalizada entre clases para medir separabilidad
    sep_pca = abs(np.mean(Z_pca_circ[y_circulos == 0, 0]) - np.mean(Z_pca_circ[y_circulos == 1, 0]))
    sep_kpca = abs(np.mean(Z_kpca[y_circulos == 0, 0]) - np.mean(Z_kpca[y_circulos == 1, 0]))

    print("=== Validación 2: Kernel PCA en Manifold Concéntrico ===")
    print(f"Separación lineal en Componente 1 (PCA Lineal): {sep_pca:.4f} (Incapaz de separar)")
    print(f"Separación no lineal en Componente 1 (Kernel PCA): {sep_kpca:.4f} (Separación limpia lograda)")
    print(f"Autovalores dominantes de Kernel: {kpca.lambdas_}")
```

---

## 7. Directrices de Razonamiento para los Modelos de Inteligencia Artificial en Prig IDE

Cuando un modelo de lenguaje en Prig IDE diseñe, audite o implemente reducciones de dimensionalidad basadas en **PCA** (`sklearn.decomposition.PCA`, `IncrementalPCA`, `KernelPCA`), aplicará de manera obligatoria las siguientes directrices técnicas:

1. **Estandarización Previa Ineludible (`StandardScaler`):**
   - PCA es sumamente sensible a las unidades de medida. Si una variable está en kilómetros y otra en milímetros, la segunda tendrá una varianza $10^6$ veces mayor y acaparará artificialmente el primer autovector sin aportar valor informativo real.
   - Todo pipeline con PCA debe anteponer un `StandardScaler()` a menos que todas las variables provengan de la misma escala física homogénea (e.g. intensidades de píxeles normalizadas $[0, 1]$ o espectros de frecuencia estandarizados).

2. **Prevención de Fugas de Información (*Data Leakage*):**
   - **Prohibición:** Jamás ajustar el centrado (`fit`) sobre el dataset completo antes de particionar en Train/Validation/Test.
   - El vector de medias $\mu$ y la base ortonormal $V_k$ deben aprenderse **únicamente sobre el subconjunto de entrenamiento**. En validación y prueba se aplica únicamente `transform(X_test)` utilizando la media y autovectores de entrenamiento congelados.

3. **Selección del Resolvedor SVD (`svd_solver`):**
   - `svd_solver='auto'`: Opción por defecto recomendada en scikit-learn.
   - `svd_solver='randomized'`: Obligatorio cuando $N > 10,000$ o $D > 500$ y se solicitan pocas componentes ($k \ll D$), acelerando el cómputo en un orden de magnitud con pérdidas despreciables de precisión.
   - `IncrementalPCA`: Activar cuando el dataset excede la capacidad de la memoria RAM del sistema (`MemoryError`), procesando lotes con `partial_fit`.

4. **Límites de Interpretabilidad y Causalidad:**
   - Recordar al usuario que las componentes principales son **combinaciones lineales densas** de todas las variables originales. No tienen interpretación física unívoca.
   - Si el usuario requiere interpretabilidad de variables clave, sugerir `SparsePCA` (que fuerza coeficientes nulos mediante regularización $\ell_1$) o técnicas de selección supervisada (*feature importance* en Random Forest/Lasso).

5. **Detección y Manejo de No Linealidad:**
   - Si la visualización bidimensional con PCA revela curvas intrincadas o si el rendimiento de un clasificador lineal no mejora tras la reducción, diagnosticar que los datos yacen en un *manifold* no lineal.
   - Recomendar la transición hacia **Kernel PCA** (con kernel RBF) para proyección estricta de espacios de Hilbert o hacia **UMAP / t-SNE** si el objetivo principal es la visualización exploratoria no supervisada.
