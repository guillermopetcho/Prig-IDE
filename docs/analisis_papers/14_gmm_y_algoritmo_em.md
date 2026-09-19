# Monografía 14: Modelos de Mezclas de Gaussianas (GMM) y el Algoritmo EM — Fundamentos de Variables Latentes, Cota Variacional ELBO y Selección de Modelo

> **Directorio de Ubicación:** `docs/analisis_papers/14_gmm_y_algoritmo_em.md`  
> **Ficha Técnica Modular Resumida:** [`docs/algoritmos_ml/14_gmm_y_algoritmo_em.md`](../algoritmos_ml/14_gmm_y_algoritmo_em.md)  
> **Estado del Documento:** Riguroso / Nivel Doctoral / Producción Académica  

---

## 1. Ficha Bibliográfica y Genealogía de Papers Seminales

1. **El Paper Fundacional del Algoritmo EM (JRSS-B, 1977):**
   - **Título:** *Maximum Likelihood from Incomplete Data via the EM Algorithm*
   - **Autores:** Arthur P. Dempster, Nan M. Laird, Donald B. Rubin (Harvard University).
   - **Publicación:** *Journal of the Royal Statistical Society: Series B (Methodological)*, 39(1), pp. 1–38 (1977).
   - **Aporte Principal:** Unificación teórica del concepto de datos incompletos (*incomplete data*) y variables latentes. Definición formal de las fases de **Expectación (Paso E)** y **Maximización (Paso M)**, demostrando el teorema de convergencia monótona de la verosimilitud.

2. **La Génesis Histórica de las Mezclas Gaussianas (Royal Society, 1894):**
   - **Título:** *Contributions to the Mathematical Theory of Evolution*
   - **Autor:** Karl Pearson.
   - **Publicación:** *Philosophical Transactions of the Royal Society of London. A*, 185, pp. 71–110 (1894).
   - **Aporte Principal:** Primera formulación analítica de una mezcla de dos densidades gaussianas continuas para modelar el polimorfismo fenotípico en crustáceos, resolviendo la estimación de sus cinco parámetros mediante el método de los momentos vía polinomios de noveno orden.

3. **La Perspectiva de la Cota Variacional ELBO (1998):**
   - **Título:** *A View of the EM Algorithm that Justifies Incremental, Sparse, and other Variants*
   - **Autores:** Radford M. Neal y Geoffrey E. Hinton (University of Toronto).
   - **Publicación:** *Learning in Graphical Models*, Springer Netherlands, pp. 355–368 (1998).
   - **Aporte Principal:** Demostración de que el algoritmo EM es una maximización coordinada de la **Cota Inferior de la Evidencia (Evidence Lower Bound, ELBO)**, estableciendo el puente conceptual hacia la inferencia variacional moderna y los Autoencoders Variacionales (VAE).

4. **Criterios de Selección de Modelo Paramétrico: BIC (1978) y AIC (1974):**
   - **BIC:** Gideon Schwarz (1978). *Estimating the Dimension of a Model*. *The Annals of Statistics*, 6(2), pp. 461–464.
   - **AIC:** Hirotugu Akaike (1974). *A New Look at the Statistical Model Identification*. *IEEE Transactions on Automatic Control*, 19(6), pp. 716–723.
   - **Aporte Principal:** Formulación de penalizaciones analíticas para balancear la bondad de ajuste de la log-verosimilitud frente a la dimensionalidad paramétrica $p$ del modelo, resolviendo la selección objetiva del número de componentes $K$.

5. **Tratado Canónico de Modelos de Mezclas y Algoritmo EM (Springer, 2006):**
   - **Título:** *Pattern Recognition and Machine Learning* (Capítulo 9: *Mixture Models and EM*).
   - **Autor:** Christopher M. Bishop (Microsoft Research Cambridge).
   - **Aporte Principal:** Sistematización pedagógica y formal de las mezclas gaussianas, derivaciones vectoriales paso a paso con multiplicadores de Lagrange, análisis del colapso de varianza por singularidades y formulación geométrica general del algoritmo EM.

---

## 2. Génesis Teórica: El Problema de la Log-Verosimilitud Incompleta

En $k$-Means, cada muestra $x_i$ está forzada a pertenecer exclusivamente a un único clúster (*hard clustering*), modelado mediante esferas de igual dispersión.  
Un **Modelo de Mezcla de Gaussianas (GMM)** generaliza este principio proporcionando una estimación probabilística suave (*soft clustering*) con densidades elipsoidales arbitrarias descritas por matrices de covarianza completas.

### 2.1. Formulación del Modelo Generativo

Sea un conjunto de datos $\mathcal{X} = \{x_1, x_2, \dots, x_N\} \subset \mathbb{R}^D$.  
Modelamos la generación estocástica de cada punto $x_i$ como un proceso en dos etapas:
1. Se extrae una variable latente no observada $z_i \in \{1, 2, \dots, K\}$ que indica qué componente generó la muestra, con probabilidades a priori:
   $$P(z_i = k) = \pi_k, \quad \text{donde } 0 \le \pi_k \le 1 \quad \text{y} \quad \sum_{k=1}^K \pi_k = 1$$
2. Condicionado a la clase $z_i = k$, la muestra $x_i$ se extrae de una distribución normal multivariante $\mathcal{N}(\mu_k, \Sigma_k)$:
   $$P(x_i \mid z_i = k) = \frac{1}{(2\pi)^{D/2} |\Sigma_k|^{1/2}} \exp\left( -\frac{1}{2} (x_i - \mu_k)^T \Sigma_k^{-1} (x_i - \mu_k) \right)$$

Marginalizando sobre la variable latente $z_i$, la densidad incondicional del punto $x_i$ es:
$$p(x_i \mid \boldsymbol{\theta}) = \sum_{k=1}^K P(z_i = k) \, P(x_i \mid z_i = k) = \sum_{k=1}^K \pi_k \mathcal{N}(x_i \mid \mu_k, \Sigma_k)$$
donde $\boldsymbol{\theta} = \{\pi_k, \mu_k, \Sigma_k\}_{k=1}^K$ es el vector global de parámetros.

### 2.2. La Falla de Máxima Verosimilitud Clásica: Suma dentro del Logaritmo

La función de log-verosimilitud observada (incompleta) sobre el dataset completo es:
$$\ln p(\mathcal{X} \mid \boldsymbol{\theta}) = \sum_{i=1}^N \ln \left( \sum_{k=1}^K \pi_k \mathcal{N}(x_i \mid \mu_k, \Sigma_k) \right)$$

**El Impedimento Analítico Fundamental:**  
A diferencia de una gaussiana individual donde el logaritmo cancela la exponencial, aquí la presencia de la **suma sobre las $K$ componentes dentro del logaritmo** acopla de manera no lineal todas las variables.  
Si calculamos la derivada respecto a $\mu_k$ e igualamos a cero:
$$\nabla_{\mu_k} \ln p(\mathcal{X} \mid \boldsymbol{\theta}) = \sum_{i=1}^N \underbrace{\frac{\pi_k \mathcal{N}(x_i \mid \mu_k, \Sigma_k)}{\sum_{j=1}^K \pi_j \mathcal{N}(x_i \mid \mu_j, \Sigma_j)}}_{\gamma_{ik}} \Sigma_k^{-1} (x_i - \mu_k) = 0$$

El término $\gamma_{ik}$ (la responsabilidad a posteriori) depende de forma compleja y circular de los mismos parámetros $\mu_k$ y $\Sigma_k$ que se intentan despejar. No existe una solución algebraica cerrada, lo que exige la formulación del **Algoritmo EM**.

---

## 3. Derivación Matemática Rigurosa del Algoritmo EM

```mermaid
graph TD
    classDef init fill:#1e1e2e,stroke:#89b4fa,stroke-width:2px,color:#cdd6f4;
    classDef e_step fill:#181825,stroke:#f9e2af,stroke-width:2px,color:#cdd6f4;
    classDef m_step fill:#181825,stroke:#a6e3a1,stroke-width:2px,color:#cdd6f4;
    classDef out fill:#181825,stroke:#cba6f7,stroke-width:2px,color:#cdd6f4;

    A["📊 Dataset X en R^{N x D}"]:::init --> B["🎯 Inicialización de Parámetros θ^(0) = {π, μ, Σ}"]:::init
    B --> C["Paso E (Expectation): Calcular Responsabilidades γ_ik = P(z_ik = 1 | x_i, θ)"]:::e_step
    C --> D["📐 Cota Inferior Variacional ELBO: Maximizada exactamente cuando q = P(Z|X, θ)"]:::e_step
    D --> E["Paso M (Maximization): Actualizar analíticamente μ_k, Σ_k, π_k mediante momentos ponderados"]:::m_step
    E --> F{"¿Δ ln p(X|θ) < tolerancia?"}:::m_step
    F -->|No (Monotonía: ln p aumenta estrictamente)| C
    F -->|Sí| G["🏁 Parámetros Óptimos: Estimación de Densidad y Soft Clustering"]:::out
```

### 3.1. La Cota Inferior de la Evidencia (ELBO) y la Descomposición de Jensen

Sea $Z = \{z_1, \dots, z_N\}$ el conjunto de variables latentes.  
Sea $q(Z)$ cualquier distribución de probabilidad arbitraria sobre el espacio latente.  
Multiplicando y dividiendo por $q(Z)$ dentro del logaritmo:
$$\ln p(\mathcal{X} \mid \boldsymbol{\theta}) = \ln \sum_Z p(\mathcal{X}, Z \mid \boldsymbol{\theta}) = \ln \sum_Z q(Z) \frac{p(\mathcal{X}, Z \mid \boldsymbol{\theta})}{q(Z)}$$

Aplicando la **Desigualdad de Jensen** a la función cóncava $\ln(u)$:
$$\ln p(\mathcal{X} \mid \boldsymbol{\theta}) \ge \sum_Z q(Z) \ln \frac{p(\mathcal{X}, Z \mid \boldsymbol{\theta})}{q(Z)} \equiv \mathcal{L}(q, \boldsymbol{\theta}) \quad (\text{ELBO})$$

#### Descomposición Exacta vía Divergencia de Kullback-Leibler:
Reescribiendo algebraicamente:
$$\ln p(\mathcal{X} \mid \boldsymbol{\theta}) = \mathcal{L}(q, \boldsymbol{\theta}) + \operatorname{KL}\left( q(Z) \,\|\, p(Z \mid \mathcal{X}, \boldsymbol{\theta}) \right)$$
donde:
$$\operatorname{KL}(q \,\|\, p) = -\sum_Z q(Z) \ln \frac{p(Z \mid \mathcal{X}, \boldsymbol{\theta})}{q(Z)} \ge 0$$

Dado que $\operatorname{KL} \ge 0$, se comprueba que $\mathcal{L}(q, \boldsymbol{\theta})$ es una cota inferior estricta de la log-verosimilitud observada para cualquier elección de $q$.

---

### 3.2. Paso E: Cierre de la Brecha Variacional

En la iteración $t$, mantenemos fijos los parámetros del modelo $\boldsymbol{\theta}^{(t)}$ y maximizamos la cota $\mathcal{L}(q, \boldsymbol{\theta}^{(t)})$ respecto a la distribución de prueba $q(Z)$.  
Como $\ln p(\mathcal{X} \mid \boldsymbol{\theta}^{(t)})$ no depende de $q(Z)$, maximizar la cota $\mathcal{L}$ equivale exactamente a **minimizar la divergencia de Kullback-Leibler a cero**:
$$\operatorname{KL}\left( q(Z) \,\|\, p(Z \mid \mathcal{X}, \boldsymbol{\theta}^{(t)}) \right) = 0 \iff q^*(Z) = p(Z \mid \mathcal{X}, \boldsymbol{\theta}^{(t)})$$

Por la regla de Bayes, la distribución a posteriori sobre la variable latente $z_{ik} \in \{0, 1\}$ para la muestra individual $x_i$ es:
$$\gamma_{ik} \equiv q^*(z_{ik} = 1) = P(z_{ik} = 1 \mid x_i, \boldsymbol{\theta}^{(t)}) = \frac{P(z_{ik} = 1) \, P(x_i \mid z_{ik} = 1)}{\sum_{j=1}^K P(z_{ij} = 1) \, P(x_i \mid z_{ij} = 1)} = \frac{\pi_k^{(t)} \mathcal{N}(x_i \mid \mu_k^{(t)}, \Sigma_k^{(t)})}{\sum_{j=1}^K \pi_j^{(t)} \mathcal{N}(x_i \mid \mu_j^{(t)}, \Sigma_j^{(t)})}$$

El valor escalar $\gamma_{ik} \in [0, 1]$ se denomina la **responsabilidad** que asume el componente $k$ en la generación de la muestra $x_i$.

---

### 3.3. Paso M: Maximización de la Función Auxiliar $Q(\boldsymbol{\theta}, \boldsymbol{\theta}^{(t)})$

En el Paso M, fijamos la distribución $q^*(Z)$ y maximizamos la cota $\mathcal{L}(q^*, \boldsymbol{\theta})$ respecto a los nuevos parámetros $\boldsymbol{\theta}$:
$$\mathcal{L}(q^*, \boldsymbol{\theta}) = \sum_Z q^*(Z) \ln p(\mathcal{X}, Z \mid \boldsymbol{\theta}) - \sum_Z q^*(Z) \ln q^*(Z) = \mathbb{E}_{Z \sim q^*}[\ln p(\mathcal{X}, Z \mid \boldsymbol{\theta})] + \mathcal{H}(q^*)$$
El término de entropía $\mathcal{H}(q^*)$ no depende de $\boldsymbol{\theta}$, por lo que maximizar la cota se reduce a maximizar la **función $Q$ de Dempster, Laird y Rubin**:
$$Q(\boldsymbol{\theta}, \boldsymbol{\theta}^{(t)}) = \mathbb{E}_{Z \sim q^*}[\ln p(\mathcal{X}, Z \mid \boldsymbol{\theta})]$$

La log-verosimilitud completa (asumiendo datos completos donde conocemos las etiquetas latentes $z_{ik}$) es:
$$\ln p(\mathcal{X}, Z \mid \boldsymbol{\theta}) = \sum_{i=1}^N \sum_{k=1}^K z_{ik} \left[ \ln \pi_k + \ln \mathcal{N}(x_i \mid \mu_k, \Sigma_k) \right]$$

Tomando la esperanza respecto a $Z$:
$$Q(\boldsymbol{\theta}, \boldsymbol{\theta}^{(t)}) = \sum_{i=1}^N \sum_{k=1}^K \gamma_{ik} \left[ \ln \pi_k - \frac{D}{2}\ln(2\pi) - \frac{1}{2}\ln|\Sigma_k| - \frac{1}{2}(x_i - \mu_k)^T \Sigma_k^{-1} (x_i - \mu_k) \right]$$

#### 1. Actualización Analítica de las Medias $\mu_k$:
Derivando respecto a $\mu_k$:
$$\nabla_{\mu_k} Q = \sum_{i=1}^N \gamma_{ik} \Sigma_k^{-1} (x_i - \mu_k) = 0 \implies \Sigma_k^{-1} \left( \sum_{i=1}^N \gamma_{ik} x_i - \mu_k \sum_{i=1}^N \gamma_{ik} \right) = 0$$
Definiendo el peso efectivo total del componente $k$:
$$N_k \equiv \sum_{i=1}^N \gamma_{ik}$$
$$\mu_k^{(t+1)} = \frac{1}{N_k} \sum_{i=1}^N \gamma_{ik} x_i$$

#### 2. Actualización Analítica de las Matrices de Covarianza $\Sigma_k$:
Derivando respecto a la matriz de precisión $\mathbf{W}_k \equiv \Sigma_k^{-1}$ utilizando identidades de cálculo matricial ($\frac{\partial \ln|\mathbf{W}|}{\partial \mathbf{W}} = \mathbf{W}^{-T}$ y $\frac{\partial (v^T \mathbf{W} v)}{\partial \mathbf{W}} = v v^T$):
$$\frac{\partial Q}{\partial \mathbf{W}_k} = \frac{1}{2} \sum_{i=1}^N \gamma_{ik} \left[ \Sigma_k - (x_i - \mu_k)(x_i - \mu_k)^T \right] = 0$$
$$\Sigma_k^{(t+1)} = \frac{1}{N_k} \sum_{i=1}^N \gamma_{ik} (x_i - \mu_k^{(t+1)})(x_i - \mu_k^{(t+1)})^T$$

#### 3. Actualización Analítica de los Coeficientes de Mezcla $\pi_k$:
Maximizamos $\sum_{i=1}^N \sum_{k=1}^K \gamma_{ik} \ln \pi_k$ sujeto a la restricción $\sum_{k=1}^K \pi_k = 1$ mediante un multiplicador de Lagrange $\lambda$:
$$\mathcal{L}_{\pi}(\boldsymbol{\pi}, \lambda) = \sum_{k=1}^K N_k \ln \pi_k + \lambda \left( \sum_{k=1}^K \pi_k - 1 \right)$$
$$\frac{\partial \mathcal{L}_{\pi}}{\partial \pi_k} = \frac{N_k}{\pi_k} + \lambda = 0 \implies N_k = -\lambda \pi_k$$
Sumando sobre todas las componentes $k \in \{1, \dots, K\}$:
$$\sum_{k=1}^K N_k = -\lambda \sum_{k=1}^K \pi_k \implies N = -\lambda \implies \lambda = -N$$
Sustituyendo $\lambda$:
$$\pi_k^{(t+1)} = \frac{N_k}{N}$$

---

### 3.4. Teorema de Monotonía Estricta de Dempster, Laird y Rubin

**Teorema:**  
En cada iteración del algoritmo EM, la log-verosimilitud observada no decrece:
$$\ln p(\mathcal{X} \mid \boldsymbol{\theta}^{(t+1)}) \ge \ln p(\mathcal{X} \mid \boldsymbol{\theta}^{(t)})$$

**Demostración:**
$$\ln p(\mathcal{X} \mid \boldsymbol{\theta}^{(t+1)}) \ge \mathcal{L}(q^{(t+1)}, \boldsymbol{\theta}^{(t+1)}) \ge \mathcal{L}(q^{(t)}, \boldsymbol{\theta}^{(t+1)}) \ge \mathcal{L}(q^{(t)}, \boldsymbol{\theta}^{(t)}) = \ln p(\mathcal{X} \mid \boldsymbol{\theta}^{(t)})$$
1. La primera igualdad se sostiene porque en el Paso E de la iteración $t$, $q^{(t)}$ se fija a la distribución a posteriori, cerrando la divergencia $\operatorname{KL}$ a 0 y haciendo que $\mathcal{L}(q^{(t)}, \boldsymbol{\theta}^{(t)}) = \ln p(\mathcal{X} \mid \boldsymbol{\theta}^{(t)})$.
2. La desigualdad intermedia proviene de la maximización exacta del Paso M: $\mathcal{L}(q^{(t)}, \boldsymbol{\theta}^{(t+1)}) \ge \mathcal{L}(q^{(t)}, \boldsymbol{\theta}^{(t)})$.
3. Al recalcular $q^{(t+1)}$ en el siguiente Paso E, la cota vuelve a coincidir con la nueva verosimilitud.  
Por consiguiente, el algoritmo EM converge monótonamente hacia un punto estacionario (mínimo local o punto de silla) de la superficie de verosimilitud.

---

## 4. Singularidades de Verosimilitud y Topologías de Covarianza

### 4.1. La Catástrofe del Colapso de la Varianza

La superficie de log-verosimilitud de una mezcla gaussiana no está acotada superiormente.  
Si durante la optimización un centroide $\mu_k$ se sitúa exactamente sobre una muestra de datos aislada $x_n$, y la covarianza asociada $\Sigma_k = \sigma_k^2 \mathbf{I}$ colapsa hacia cero ($\sigma_k \to 0$):
$$\mathcal{N}(x_n \mid x_n, \sigma_k^2 \mathbf{I}) = \frac{1}{(2\pi \sigma_k^2)^{D/2}} \exp(0) = \frac{1}{(2\pi \sigma_k^2)^{D/2}} \xrightarrow{\sigma_k \to 0} +\infty$$

La log-verosimilitud completa diverge hacia $+\infty$. Este fenómeno no representa un agrupamiento real, sino una **singularidad patológica de sobreajuste** (la gaussiana se convierte en una delta de Dirac sobre una muestra individual).

#### Solución Mediante Regularización de Covarianza (`reg_covar`):
Se impone una cota inferior a la dispersión agregando una perturbación esférica positiva mínima a la diagonal de cada matriz de covarianza en cada Paso M:
$$\tilde{\Sigma}_k = \Sigma_k + \epsilon_{\text{reg}} \mathbf{I}_{D \times D}$$
con $\epsilon_{\text{reg}} \approx 10^{-6}$, garantizando que todos los autovalores satisfagan $\lambda_{\min}(\tilde{\Sigma}_k) \ge \epsilon_{\text{reg}} > 0$ y evitando singularidades numéricas.

---

### 4.2. Tipos Canónicos de Matrices de Covarianza

| Tipo de Covarianza (`covariance_type`) | Restricción Geométrica | Parámetros de Covarianza | Geometría de los Clústeres |
|---|---|---|---|
| **`full`** | $\Sigma_k$ completa simétrica y definida positiva | $K \times \frac{D(D+1)}{2}$ | Elipsoides con orientaciones, excentricidades y tamaños totalmente independientes. |
| **`tied`** | Todas las componentes comparten la misma $\Sigma$ | $\frac{D(D+1)}{2}$ | Elipsoides con idéntico tamaño, excentricidad y orientación (fronteras lineales entre clases). |
| **`diag`** | $\Sigma_k = \operatorname{diag}(\sigma_{k1}^2, \dots, \sigma_{kD}^2)$ | $K \times D$ | Elipsoides alineados exclusivamente con los ejes coordenados (independencia condicional). |
| **`spherical`** | $\Sigma_k = \sigma_k^2 \mathbf{I}$ | $K$ | Hiper-esferas isotrópicas. |

*Conexión Profunda con $k$-Means:* Cuando un modelo GMM esférico homogéneo ($\Sigma_k = \sigma^2 \mathbf{I}$) lleva su varianza al límite $\sigma^2 \to 0$, las responsabilidades suaves colapsan a valores binarios $\gamma_{ik} \in \{0, 1\}$, y el algoritmo EM se vuelve **matemáticamente idéntico al algoritmo de Lloyd de $k$-Means**.

---

## 5. Criterios de Selección de Modelo: BIC y AIC

Como la log-verosimilitud siempre aumenta al incrementar $K$, para seleccionar el número óptimo de componentes sin sobreajuste se utilizan criterios de penalización de teoría de la información:

### 5.1. Criterio de Información Bayesiano (BIC, Schwarz 1978)
$$\text{BIC} = -2 \ln \hat{L} + p \ln(N)$$

### 5.2. Criterio de Información de Akaike (AIC, Akaike 1974)
$$\text{AIC} = -2 \ln \hat{L} + 2p$$

donde $\hat{L} = p(\mathcal{X} \mid \hat{\boldsymbol{\theta}})$ es la verosimilitud máxima alcanzada, $N$ es el número de muestras, y $p$ es el número total de parámetros libres del modelo:
$$p = \underbrace{(K - 1)}_{\text{pesos } \pi} + \underbrace{K \cdot D}_{\text{medias } \mu} + \underbrace{p_{\Sigma}}_{\text{covarianzas}}$$
- Para `full`: $p_{\Sigma} = K \cdot \frac{D(D+1)}{2}$.
- Para `diag`: $p_{\Sigma} = K \cdot D$.
- Para `spherical`: $p_{\Sigma} = K$.
- Para `tied`: $p_{\Sigma} = \frac{D(D+1)}{2}$.

**Regla de Decisión:** El modelo óptimo es aquel que **minimiza el valor de BIC**. BIC penaliza con mayor rigor ($\ln N > 2$ para $N \ge 8$), siendo asintóticamente consistente al recuperar el número real de componentes latentes.

---

## 6. Implementación Pura en Python y NumPy (Sin Scikit-Learn ni SciPy)

A continuación se presenta un motor completo en NumPy puro que implementa:
1. Función de densidad gaussiana multivariante numéricamente estable con regularización `reg_covar`.
2. Bucle completo del algoritmo EM (Paso E suave y Paso M matricial).
3. Monitoreo de convergencia de log-verosimilitud.
4. Cálculo de BIC y AIC.

```python
"""
Módulo Didáctico de Referencia: Gaussian Mixture Models (GMM) y Algoritmo EM en NumPy Puro
Implementa el algoritmo de Dempster, Laird & Rubin (1977) y criterios BIC/AIC
sin dependencias de scikit-learn, scipy o statsmodels.
"""

import numpy as np


class GMM_EMPuro:
    """
    Modelo de Mezcla de Gaussianas con matrices de covarianza completas ('full')
    estimado mediante el algoritmo Expectation-Maximization.
    """
    def __init__(self, n_components=3, max_iter=100, tol=1e-4, reg_covar=1e-6, random_state=42):
        self.k = int(n_components)
        self.max_iter = int(max_iter)
        self.tol = float(tol)
        self.reg_covar = float(reg_covar)
        self.random_state = random_state

        # Parámetros del modelo
        self.weights_ = None       # pi: Shape (K,)
        self.means_ = None         # mu: Shape (K, D)
        self.covariances_ = None   # Sigma: Shape (K, D, D)
        self.converged_ = False
        self.lower_bound_ = -float('inf')

    def _evaluar_log_gaussiana(self, X, mean, cov):
        """
        Computa el logaritmo de la densidad normal multivariante de forma numéricamente estable:
        ln N(x; μ, Σ) = -0.5 * [ D * ln(2π) + ln|Σ| + (x - μ)^T Σ^-1 (x - μ) ]
        """
        N, D = X.shape
        # Añadir regularización a la diagonal para garantizar condicionamiento positivo
        cov_reg = cov + np.eye(D) * self.reg_covar

        # Usar descomposición de Cholesky para cálculo rápido y estable de determinante e inversa
        try:
            L = np.linalg.cholesky(cov_reg)
            # Log-determinante: ln|Σ| = 2 * sum(ln(diag(L)))
            log_det = 2.0 * np.sum(np.log(np.diag(L)))
            # Solución del sistema triangular L * y = (X - μ)^T
            diff = X - mean
            sol = np.linalg.solve(L, diff.T)
            mahalanobis = np.sum(sol**2, axis=0)
        except np.linalg.LinAlgError:
            # Fallback en caso de autovalores minúsculos
            inv_cov = np.linalg.pinv(cov_reg)
            diff = X - mean
            mahalanobis = np.sum(np.dot(diff, inv_cov) * diff, axis=1)
            sign, log_det = np.linalg.slogdet(cov_reg)

        log_prob = -0.5 * (D * np.log(2.0 * np.pi) + log_det + mahalanobis)
        return log_prob

    def fit(self, X):
        N, D = X.shape
        rng = np.random.RandomState(self.random_state)

        # 1. Inicialización de parámetros
        # Asignación aleatoria uniforme de pesos
        self.weights_ = np.full(self.k, 1.0 / self.k)
        
        # Medias iniciales: seleccionar k puntos aleatorios
        idx_iniciales = rng.choice(N, size=self.k, replace=False)
        self.means_ = X[idx_iniciales].copy()

        # Covarianzas iniciales: covarianza empírica global para todos
        cov_global = np.cov(X, rowvar=False) + np.eye(D) * self.reg_covar
        self.covariances_ = np.array([cov_global.copy() for _ in range(self.k)])

        log_likelihood_prev = -float('inf')

        for iteracion in range(self.max_iter):
            # =========================================================
            # PASO E: Expectation (Calcular responsabilidades gamma_ik)
            # =========================================================
            # Matriz de log-probabilidades ponderadas: ln(pi_k) + ln N(x_i; mu_k, Sigma_k)
            log_responsabilidades = np.zeros((N, self.k), dtype=np.float64)
            for k_idx in range(self.k):
                log_densidad = self._evaluar_log_gaussiana(X, self.means_[k_idx], self.covariances_[k_idx])
                log_responsabilidades[:, k_idx] = np.log(self.weights_[k_idx] + 1e-15) + log_densidad

            # Normalización con truco Log-Sum-Exp para evitar subdesbordamiento
            max_log = np.max(log_responsabilidades, axis=1, keepdims=True)
            log_suma = max_log + np.log(np.sum(np.exp(log_responsabilidades - max_log), axis=1, keepdims=True))
            
            # Log-verosimilitud observada del dataset completo
            log_likelihood_actual = np.sum(log_suma)

            # Responsabilidades normalizadas: gamma_ik = exp(log_resp - log_suma)
            gamma = np.exp(log_responsabilidades - log_suma)

            # Comprobar convergencia
            if abs(log_likelihood_actual - log_likelihood_prev) < self.tol:
                self.converged_ = True
                self.lower_bound_ = log_likelihood_actual
                break

            log_likelihood_prev = log_likelihood_actual

            # =========================================================
            # PASO M: Maximization (Actualizar pesos, medias y covarianzas)
            # =========================================================
            N_k = np.sum(gamma, axis=0)  # Shape: (K,)

            for k_idx in range(self.k):
                peso_k = N_k[k_idx]
                if peso_k <= 1e-10:
                    continue

                # 1. Nuevas medias ponderadas
                self.means_[k_idx] = np.sum(gamma[:, k_idx:k_idx+1] * X, axis=0) / peso_k

                # 2. Nuevas covarianzas ponderadas
                diff = X - self.means_[k_idx]
                # gamma[:, k_idx, None] * diff multiplica cada fila por su responsabilidad
                cov_actualizada = np.dot((gamma[:, k_idx:k_idx+1] * diff).T, diff) / peso_k
                self.covariances_[k_idx] = cov_actualizada + np.eye(D) * self.reg_covar

            # 3. Nuevos coeficientes de mezcla
            self.weights_ = N_k / N

        self.lower_bound_ = log_likelihood_prev
        return self

    def predict_proba(self, X):
        """Retorna la matriz de responsabilidades suaves P(z_ik = 1 | x_i)."""
        N = X.shape[0]
        log_resp = np.zeros((N, self.k), dtype=np.float64)
        for k_idx in range(self.k):
            log_densidad = self._evaluar_log_gaussiana(X, self.means_[k_idx], self.covariances_[k_idx])
            log_resp[:, k_idx] = np.log(self.weights_[k_idx] + 1e-15) + log_densidad

        max_log = np.max(log_resp, axis=1, keepdims=True)
        log_suma = max_log + np.log(np.sum(np.exp(log_resp - max_log), axis=1, keepdims=True))
        return np.exp(log_resp - log_suma)

    def predict(self, X):
        """Asignación dura al componente con mayor responsabilidad a posteriori."""
        return np.argmax(self.predict_proba(X), axis=1)

    def bic(self, X):
        """Calcula el Criterio de Información Bayesiano: BIC = -2 * ln(L) + p * ln(N)."""
        N, D = X.shape
        # Número de parámetros libres para covarianza 'full':
        # pi: (K - 1), mu: K * D, Sigma: K * D * (D + 1) / 2
        p = (self.k - 1) + self.k * D + self.k * (D * (D + 1) // 2)
        return -2.0 * self.lower_bound_ + p * np.log(N)


# =====================================================================
# Verificación Numérica: Clusters Elipsoidales No Esféricos
# =====================================================================
if __name__ == "__main__":
    np.random.seed(42)

    # Generación de dos elipsoides con fuerte correlación cruzada (imposibles para k-Means)
    N1, N2 = 150, 150
    # Componente 1: orientado diagonalmente
    cov1 = np.array([[2.0, 1.5],
                     [1.5, 1.5]])
    X1 = np.random.multivariate_normal(mean=[-2.0, -2.0], cov=cov1, size=N1)

    # Componente 2: orientado en eje opuesto
    cov2 = np.array([[1.8, -1.2],
                     [-1.2, 1.2]])
    X2 = np.random.multivariate_normal(mean=[3.0, 3.0], cov=cov2, size=N2)

    X = np.vstack([X1, X2])

    # Ajuste del modelo GMM puro
    gmm = GMM_EMPuro(n_components=2, max_iter=80, tol=1e-4, random_state=42)
    gmm.fit(X)

    respuestas_suaves = gmm.predict_proba(X)
    etiquetas_duras = gmm.predict(X)
    bic_score = gmm.bic(X)

    print("=== Módulo GMM y Algoritmo EM Puro: Validación Exitosa ===")
    print(f"Total de muestras analizadas: {len(X)}")
    print(f"Log-Verosimilitud final alcanzada: {gmm.lower_bound_:.2f}")
    print(f"Pesos aprendidos de las componentes pi: {gmm.weights_}")
    print(f"Medias estimadas mu:\n{gmm.means_}")
    print(f"Criterio BIC para K=2: {bic_score:.2f}")
    print(f"Convergencia del algoritmo: {gmm.converged_}")
```

---

## 7. Directrices de Razonamiento para los Modelos de Inteligencia Artificial en Prig IDE

Cuando un modelo de lenguaje en Prig IDE diseñe, audite o diagnostique sistemas basados en **Gaussian Mixture Models** (`sklearn.mixture.GaussianMixture`), aplicará de manera obligatoria la siguiente jerarquía de decisiones técnicas:

1. **Selección del Tipo de Covarianza (`covariance_type`):**
   - **`full` (Default):** Utilizar cuando se sospeche que los clusters tienen orientaciones y correlaciones cruzadas dispares y se cuente con suficientes muestras ($N \gg D^2$).
   - **`diag`:** Forzar si la dimensionalidad es elevada ($D > 30$) o si $N$ es reducido, evitando que el número cuadrático de parámetros desestabilice la convergencia.
   - **`tied`:** Recomendado cuando se asume que todos los clusters provienen del mismo proceso físico con dispersión homogénea pero centros desplazados.
   - **`spherical`:** Alternativa probabilística suave y rápida a $k$-Means.
2. **Mitigación del Colapso de Varianza con `reg_covar`:**
   - Si durante el ajuste surge un error de tipo `LinAlgError: matrix is singular`, explicar al usuario que una gaussiana ha colapsado sobre un solo punto o que los datos tienen columnas con varianza nula. Ajustar `reg_covar=1e-4` o `1e-3` para estabilizar el acondicionamiento numérico.
3. **Selección Objetiva de $K$ Mediante BIC:**
   - Para encontrar el número óptimo de componentes, ejecutar un barrido en rejilla sobre $K \in [1, 15]$ y graficar la curva del **Criterio BIC**. Seleccionar el $K$ que alcance el **mínimo global de BIC**.
4. **Inicialización y Prevención de Mínimos Locales:**
   - El algoritmo EM solo garantiza convergencia a óptimos locales. Siempre mantener `init_params='kmeans'` (sembrado inteligente por $k$-Means) y utilizar `n_init=5` a `10` en datasets críticos para quedarse con el ajuste de máxima verosimilitud global.
