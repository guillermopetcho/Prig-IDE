# Análisis Exhaustivo de Papers Seminales: Modelos Probabilísticos de Difusión (DDPM, Score-Based SDE y Latent Diffusion)

---

## 1. Ficha Bibliográfica y Contexto Histórico-Científico

### 1.1. Las Publicaciones Fundacionales

* **Paper Seminal de DDPM (Denoising Diffusion Probabilistic Models):**
  * **Título:** *Denoising Diffusion Probabilistic Models*
  * **Autores:** Jonathan Ho, Ajay Jain, Pieter Abbeel.
  * **Afiliación:** University of California, Berkeley (UC Berkeley).
  * **Fecha de Publicación:** 19 de junio de 2020 (arXiv:2006.11239); *Advances in Neural Information Processing Systems (NeurIPS 2020)*, Vol. 33, pp. 6840-6851.
  * **Impacto Histórico:** Transformó la inteligencia artificial generativa al demostrar que los modelos de difusión podían superar la calidad de síntesis visual de las Redes Generativas Antagónicas (GANs), erradicando por completo los problemas de inestabilidad de entrenamiento y colapso de modo (*mode collapse*).

* **Precursor Físico-Estadístico:**
  * **Título:** *Deep Unsupervised Learning using Nonequilibrium Thermodynamics*
  * **Autores:** Jascha Sohl-Dickstein, Eric A. Weiss, Niru Maheswaranathan, Surya Ganguli.
  * **Afiliación:** Stanford University.
  * **Fecha de Publicación:** 12 de marzo de 2015 (arXiv:1503.03585); *Proceedings of the 32nd International Conference on Machine Learning (ICML 2015)*, Lille, Francia.
  * **Contribución:** Formuló por primera vez el modelado generativo como la inversión temporal de un proceso de difusión termodinámica no en equilibrio que destruye información mediante una cadena de Markov gaussiana.

* **La Unificación Matemática con Ecuaciones Diferenciales Estocásticas (Score-Based SDE):**
  * **Título:** *Score-Based Generative Modeling through Stochastic Differential Equations*
  * **Autores:** Yang Song, Jascha Sohl-Dickstein, Diederik P. Kingma, Abhishek Kumar, Stefano Ermon, Ben Poole.
  * **Afiliación:** Stanford University, Google Brain.
  * **Fecha de Publicación:** 26 de noviembre de 2020 (arXiv:2011.13456); *International Conference on Learning Representations (ICLR 2021)* (Oral).
  * **Contribución:** Demostró que DDPM y los modelos basados en puntaje (*Score Matching*) son casos particulares discretizados en el tiempo de Ecuaciones Diferenciales Estocásticas (SDE) de Itô en tiempo continuo, deduciendo además la ODE de flujo de probabilidad (*Probability Flow ODE*).

* **Aceleración No Markoviana y Espacio Latente:**
  * **DDIM (Denoising Diffusion Implicit Models):** Jiaming Song, Chenlin Meng, Stefano Ermon (2020). *Denoising Diffusion Implicit Models*. ICLR 2021. Eliminación de la estocasticidad en la inferencia, permitiendo saltar de 1000 pasos de muestreo a 20-50 pasos deterministas con trayectorias invertibles.
  * **Cronograma Cosenoidal y Varianza Aprendida:** Alex Nichol, Prafulla Dhariwal (2021). *Improved Denoising Diffusion Probabilistic Models*. ICML 2021. Propuso el cronograma cosenoidal de varianzas $\bar{\alpha}_t$ para evitar la destrucción prematura de señal en imágenes pequeñas.
  * **Classifier-Free Guidance (CFG):** Jonathan Ho, Tim Salimans (2021). *Classifier-Free Diffusion Guidance*. NeurIPS Workshop 2021. Eliminó la necesidad de un clasificador externo para guiar la generación condicional.
  * **Latent Diffusion Models (Stable Diffusion):** Robin Rombach, Andreas Blattmann, Dominik Lorenz, Patrick Esser, Björn Ommer (2022). *High-Resolution Image Synthesis with Latent Diffusion Models*. CVPR 2022. Desplazamiento del proceso de difusión desde el espacio de píxeles de alta resolución al espacio latente comprimido de un autoencoder perceptual.

---

## 2. Génesis Teórica y Ruptura de Paradigma

### 2.1. Las Falencias de los Modelos Generativos Tradicionales

Hacia el año 2020, la síntesis generativa profunda estaba fragmentada en cuatro familias que obligaban a elegir entre calidad perceptual, estabilidad de entrenamiento o velocidad de muestreo:

```
Panorama de Modelos Generativos Previos a la Difusión:

1. GANs (Goodfellow 2014):
   Ruido z ---> [ Generador G ] ---> x_falso \
                                             +---> [ Discriminador D ] ---> Minimax
   Datos reales -------------------> x_real  /
   * Defecto Fatal: Juego adversarial minimax min_G max_D inestable; "Mode Collapse" crónico;
     sin estimación de densidad probabilística tratable.

2. VAEs (Kingma & Welling 2013):
   x ---> [ Encoder q_phi ] ---> Espacio Latente z ---> [ Decoder p_theta ] ---> x_recon
   * Defecto Fatal: Muestras borrosas por aproximación gaussiana diagonal e incompetencia
     para capturar texturas de alta frecuencia con pérdidas L2.

3. Modelos Autoregresivos (PixelCNN, PixelRNN):
   p(x) = Prod_i p(x_i | x_{<i})
   * Defecto Fatal: Muestreo estrictamente secuencial O(N); inferencia inviable a escala.

4. Flujos Normalizadores (RealNVP, Glow):
   Transformaciones biyectivas invertibles x <---> z
   * Defecto Fatal: Restricción severa de jacobianos triangulares tratables; enorme huella en VRAM.
```

### 2.2. La Intuición Termodinámica de la Difusión
Inspirándose en la física estadística de no equilibrio, Sohl-Dickstein et al. (2015) y Ho et al. (2020) concibieron la generación de datos no como un salto repentino de una distribución latente simple a una imagen compleja, sino como la **inversión controlada de un proceso físico de degradación gradual**.

Si una gota de tinta azul se introduce en un vaso de agua pura, las colisiones moleculares brownianas dispersan progresivamente las moléculas de tinta hasta que el líquido alcanza un estado homogéneo e indistinguible de máxima entropía (ruido gaussiano isotrópico). Este proceso natural (forward) es trivial y destruye sistemáticamente toda la estructura semántica de la tinta.

El desafío generativo consiste en **invertir la flecha del tiempo termodinámica**: partir de agua con tinta completamente dispersa (ruido puro) y guiar infinitesimalmente cada partícula para que regrese a la forma de la gota original.

Dado que cada paso individual de difusión añade únicamente una cantidad microscópica de perturbación gaussiana, la distribución inversa paso a paso $q(x_{t-1} \mid x_t)$ es **también una distribución gaussiana analítica** (conforme al teorema fundamental de inversión estocástica de Feller, 1949). La red neuronal no tiene que aprender la caótica distribución multivariable completa de los datos, sino una tarea infinitamente más sencilla y bien condicionada: estimar la pequeña media de reducción de ruido en cada paso temporal discreto.

---

## 3. Formulación y Derivaciones Matemáticas Rigurosas

```
Esquema Temporal Bidireccional de DDPM:

  Proceso Forward q (Fijo, Markoviano, Añade Ruido Gaussiano Progresivo):
  x_0 ----------> x_1 ----------> x_2 ----------> ... ----------> x_{T-1} ----------> x_T ~ N(0, I)
   |                                                                                   ^
   +==================== Salto Analítico Directo q(x_t | x_0) =========================+

  Proceso Reverse p_theta (Aprendible, Red Neuronal U-Net, Elimina Ruido):
  x_0 <---------- x_1 <---------- x_2 <---------- ... <---------- x_{T-1} <---------- x_T ~ N(0, I)
           p_theta(x_0|x_1)               p_theta(x_{t-1}|x_t)
```

---

### 3.1. Proceso Forward de Cadena de Markov

Dada una muestra de datos real $x_0 \sim q(x_0)$, el proceso forward es una cadena de Markov no aprendible parametrizada por un cronograma de varianzas creciente $\beta_1, \beta_2, \dots, \beta_T \in (0, 1)$:
$$q(x_{1:T} \mid x_0) = \prod_{t=1}^T q(x_t \mid x_{t-1})$$
donde cada transición condicional es una distribución normal multivariada:
$$q(x_t \mid x_{t-1}) = \mathcal{N}\left(x_t; \sqrt{1 - \beta_t} x_{t-1}, \beta_t I\right)$$

*Nota Geométrica:* El factor $\sqrt{1 - \beta_t}$ actúa como un coeficiente de amortiguamiento que asegura que si $\text{Var}(x_{t-1}) \approx 1$, entonces $\text{Var}(x_t) = (1 - \beta_t)\text{Var}(x_{t-1}) + \beta_t = (1 - \beta_t)(1) + \beta_t = 1$. La varianza total se mantiene rigurosamente normalizada en cada paso temporal.

---

### 3.2. Teorema y Deducción: El Salto Analítico Directo $q(x_t \mid x_0)$

Una debilidad inmediata del proceso forward sería tener que iterar secuencialmente $t$ veces a través de la cadena para obtener una muestra ruidosa $x_t$. Afortunadamente, existe una forma cerrada analítica que permite saltar directamente desde $x_0$ a cualquier $x_t$ arbitrario en $\mathcal{O}(1)$.

#### Definición de Notación
Definimos:
$$\alpha_t = 1 - \beta_t, \quad \bar{\alpha}_t = \prod_{s=1}^t \alpha_s$$

#### Demostración por Inducción Matemática
Utilizando el truco de reparametrización gaussiana ($x \sim \mathcal{N}(\mu, \sigma^2 I) \iff x = \mu + \sigma \epsilon$ con $\epsilon \sim \mathcal{N}(0, I)$):
* Para $t = 1$:
  $$x_1 = \sqrt{\alpha_1} x_0 + \sqrt{1 - \alpha_1} \epsilon_0, \quad \text{donde } \epsilon_0 \sim \mathcal{N}(0, I)$$
* Para $t = 2$:
  $$x_2 = \sqrt{\alpha_2} x_1 + \sqrt{1 - \alpha_2} \epsilon_1, \quad \text{donde } \epsilon_1 \sim \mathcal{N}(0, I)$$
  Sustituyendo $x_1$:
  $$x_2 = \sqrt{\alpha_2}\left( \sqrt{\alpha_1} x_0 + \sqrt{1 - \alpha_1} \epsilon_0 \right) + \sqrt{1 - \alpha_2} \epsilon_1 = \sqrt{\alpha_1 \alpha_2} x_0 + \sqrt{\alpha_2(1 - \alpha_1)} \epsilon_0 + \sqrt{1 - \alpha_2} \epsilon_1$$

* **Propiedad de Suma de Variables Gaussianas Independientes:**
  Sean dos variables normales independientes $X_a \sim \mathcal{N}(0, \sigma_a^2 I)$ y $X_b \sim \mathcal{N}(0, \sigma_b^2 I)$. Su combinación lineal es también normal con varianza suma:
  $$X_a + X_b \sim \mathcal{N}(0, (\sigma_a^2 + \sigma_b^2) I)$$
  En nuestro caso:
  $$\sigma_{\text{comb}}^2 = \left( \sqrt{\alpha_2(1 - \alpha_1)} \right)^2 + \left( \sqrt{1 - \alpha_2} \right)^2 = \alpha_2(1 - \alpha_1) + 1 - \alpha_2 = \alpha_2 - \alpha_1 \alpha_2 + 1 - \alpha_2 = 1 - \alpha_1 \alpha_2$$
  Por lo tanto, podemos consolidar ambos términos estocásticos en una única variable normal estándar $\epsilon_{12} \sim \mathcal{N}(0, I)$:
  $$x_2 = \sqrt{\alpha_1 \alpha_2} x_0 + \sqrt{1 - \alpha_1 \alpha_2} \epsilon_{12}$$

* **Paso Inductivo General:**
  Asumiendo que $x_{t-1} = \sqrt{\bar{\alpha}_{t-1}} x_0 + \sqrt{1 - \bar{\alpha}_{t-1}} \epsilon_{t-1}$:
  $$x_t = \sqrt{\alpha_t} x_{t-1} + \sqrt{1 - \alpha_t} \epsilon = \sqrt{\alpha_t}\left( \sqrt{\bar{\alpha}_{t-1}} x_0 + \sqrt{1 - \bar{\alpha}_{t-1}} \epsilon_{t-1} \right) + \sqrt{1 - \alpha_t} \epsilon$$
  $$= \sqrt{\alpha_t \bar{\alpha}_{t-1}} x_0 + \sqrt{\alpha_t(1 - \bar{\alpha}_{t-1})} \epsilon_{t-1} + \sqrt{1 - \alpha_t} \epsilon$$
  Sumando las varianzas:
  $$\sigma_t^2 = \alpha_t(1 - \bar{\alpha}_{t-1}) + 1 - \alpha_t = \alpha_t - \alpha_t \bar{\alpha}_{t-1} + 1 - \alpha_t = 1 - \alpha_t \bar{\alpha}_{t-1} = 1 - \bar{\alpha}_t$$
  Queda demostrado analíticamente el resultado:
  $$x_t = \sqrt{\bar{\alpha}_t} x_0 + \sqrt{1 - \bar{\alpha}_t} \epsilon, \quad \text{donde } \epsilon \sim \mathcal{N}(0, I)$$
  $$q(x_t \mid x_0) = \mathcal{N}\left(x_t; \sqrt{\bar{\alpha}_t} x_0, (1 - \bar{\alpha}_t) I\right)$$

Esta ecuación es la piedra angular del entrenamiento eficiente de DDPM: permite generar pares de entrenamiento $(x_t, t)$ muestreando uniformemente cualquier paso temporal $t \in \{1, \dots, T\}$ en un solo paso de multiplicación tensorial.

---

### 3.3. Distribución Posterior Tratable Condicionada a $x_0$ ($q(x_{t-1} \mid x_t, x_0)$)

La distribución inversa marginal $q(x_{t-1} \mid x_t)$ es intratable porque requiere integrar sobre toda la variedad de datos: $q(x_{t-1} \mid x_t) = \int q(x_{t-1}, x_0 \mid x_t) dx_0$.
Sin embargo, cuando condicionamos en la muestra limpia original $x_0$, la distribución posterior se vuelve completamente tratable mediante el Teorema de Bayes:
$$q(x_{t-1} \mid x_t, x_0) = q(x_t \mid x_{t-1}, x_0) \frac{q(x_{t-1} \mid x_0)}{q(x_t \mid x_0)} = q(x_t \mid x_{t-1}) \frac{q(x_{t-1} \mid x_0)}{q(x_t \mid x_0)}$$

Sustituyendo las funciones de densidad de probabilidad gaussianas correspondientes:
$$q(x_t \mid x_{t-1}) \propto \exp\left( -\frac{\|x_t - \sqrt{\alpha_t} x_{t-1}\|^2}{2 \beta_t} \right)$$
$$q(x_{t-1} \mid x_0) \propto \exp\left( -\frac{\|x_{t-1} - \sqrt{\bar{\alpha}_{t-1}} x_0\|^2}{2(1 - \bar{\alpha}_{t-1})} \right)$$
$$q(x_t \mid x_0) \propto \exp\left( -\frac{\|x_t - \sqrt{\bar{\alpha}_t} x_0\|^2}{2(1 - \bar{\alpha}_t)} \right)$$

El exponente total es:
$$\text{Exp} = -\frac{1}{2} \left[ \frac{(x_t - \sqrt{\alpha_t} x_{t-1})^2}{\beta_t} + \frac{(x_{t-1} - \sqrt{\bar{\alpha}_{t-1}} x_0)^2}{1 - \bar{\alpha}_{t-1}} - \frac{(x_t - \sqrt{\bar{\alpha}_t} x_0)^2}{1 - \bar{\alpha}_t} \right]$$

Expandiendo los términos cuadráticos respecto a la variable desconocida $x_{t-1}$:
$$\text{Exp} = -\frac{1}{2} \left[ x_{t-1}^2 \left( \frac{\alpha_t}{\beta_t} + \frac{1}{1 - \bar{\alpha}_{t-1}} \right) - 2 x_{t-1} \left( \frac{\sqrt{\alpha_t} x_t}{\beta_t} + \frac{\sqrt{\bar{\alpha}_{t-1}} x_0}{1 - \bar{\alpha}_{t-1}} \right) + C(x_t, x_0) \right]$$

Identificando la forma canónica de una gaussiana unidimensional en el exponente $-\frac{1}{2 \sigma^2}(x - \mu)^2 = -\frac{1}{2}\left( \frac{1}{\sigma^2} x^2 - \frac{2\mu}{\sigma^2} x + \frac{\mu^2}{\sigma^2} \right)$:

1. **Varianza Posterior ($\tilde{\beta}_t$):**
   $$\frac{1}{\tilde{\beta}_t} = \frac{\alpha_t}{\beta_t} + \frac{1}{1 - \bar{\alpha}_{t-1}} = \frac{\alpha_t(1 - \bar{\alpha}_{t-1}) + \beta_t}{\beta_t(1 - \bar{\alpha}_{t-1})} = \frac{\alpha_t - \bar{\alpha}_t + 1 - \alpha_t}{\beta_t(1 - \bar{\alpha}_{t-1})} = \frac{1 - \bar{\alpha}_t}{\beta_t(1 - \bar{\alpha}_{t-1})}$$
   Invirtiendo la fracción:
   $$\tilde{\beta}_t = \frac{1 - \bar{\alpha}_{t-1}}{1 - \bar{\alpha}_t} \beta_t$$

2. **Media Posterior ($\tilde{\mu}_t(x_t, x_0)$):**
   $$\frac{\tilde{\mu}_t}{\tilde{\beta}_t} = \frac{\sqrt{\alpha_t}}{\beta_t} x_t + \frac{\sqrt{\bar{\alpha}_{t-1}}}{1 - \bar{\alpha}_{t-1}} x_0$$
   Multiplicando por $\tilde{\beta}_t$:
   $$\tilde{\mu}_t(x_t, x_0) = \left( \frac{\sqrt{\alpha_t}}{\beta_t} x_t + \frac{\sqrt{\bar{\alpha}_{t-1}}}{1 - \bar{\alpha}_{t-1}} x_0 \right) \frac{\beta_t(1 - \bar{\alpha}_{t-1})}{1 - \bar{\alpha}_t}$$
   $$\tilde{\mu}_t(x_t, x_0) = \frac{\sqrt{\alpha_t}(1 - \bar{\alpha}_{t-1})}{1 - \bar{\alpha}_t} x_t + \frac{\sqrt{\bar{\alpha}_{t-1}} \beta_t}{1 - \bar{\alpha}_t} x_0$$

#### Reexpresión de la Media en Función del Ruido Inyectado $\epsilon$
Dado que por el salto directo sabemos que $x_t = \sqrt{\bar{\alpha}_t} x_0 + \sqrt{1 - \bar{\alpha}_t} \epsilon$, despejamos $x_0$:
$$x_0 = \frac{x_t - \sqrt{1 - \bar{\alpha}_t} \epsilon}{\sqrt{\bar{\alpha}_t}}$$
Sustituyendo esta identidad en la media posterior:
$$\tilde{\mu}_t(x_t, x_0) = \frac{\sqrt{\alpha_t}(1 - \bar{\alpha}_{t-1})}{1 - \bar{\alpha}_t} x_t + \frac{\sqrt{\bar{\alpha}_{t-1}} \beta_t}{1 - \bar{\alpha}_t} \left( \frac{x_t - \sqrt{1 - \bar{\alpha}_t} \epsilon}{\sqrt{\bar{\alpha}_t}} \right)$$
Agrupando los coeficientes de $x_t$ y recordando que $\sqrt{\bar{\alpha}_t} = \sqrt{\alpha_t}\sqrt{\bar{\alpha}_{t-1}}$:
$$\text{Coef}(x_t) = \frac{\sqrt{\alpha_t}(1 - \bar{\alpha}_{t-1})}{1 - \bar{\alpha}_t} + \frac{\sqrt{\bar{\alpha}_{t-1}} \beta_t}{(1 - \bar{\alpha}_t)\sqrt{\alpha_t}\sqrt{\bar{\alpha}_{t-1}}} = \frac{\alpha_t(1 - \bar{\alpha}_{t-1}) + \beta_t}{\sqrt{\alpha_t}(1 - \bar{\alpha}_t)} = \frac{1 - \bar{\alpha}_t}{\sqrt{\alpha_t}(1 - \bar{\alpha}_t)} = \frac{1}{\sqrt{\alpha_t}}$$
Y el término de $\epsilon$:
$$\text{Coef}(\epsilon) = -\frac{\sqrt{\bar{\alpha}_{t-1}}\beta_t \sqrt{1 - \bar{\alpha}_t}}{(1 - \bar{\alpha}_t)\sqrt{\alpha_t}\sqrt{\bar{\alpha}_{t-1}}} = -\frac{\beta_t}{\sqrt{\alpha_t}\sqrt{1 - \bar{\alpha}_t}}$$

Se obtiene la célebre ecuación de Ho et al.:
$$\tilde{\mu}_t(x_t, \epsilon) = \frac{1}{\sqrt{\alpha_t}} \left( x_t - \frac{\beta_t}{\sqrt{1 - \bar{\alpha}_t}} \epsilon \right)$$

Esta demostración prueba que si conocemos el ruido $\epsilon$ que corrompió la imagen en el paso $t$, podemos calcular con exactitud analítica la media del paso previo $x_{t-1}$.

---

### 3.4. Derivación de la Cota Inferior Variacional (ELBO) y la Pérdida $L_{\text{simple}}$

El objetivo del modelo generativo es maximizar la verosimilitud marginal de los datos reales $\mathbb{E}_{q(x_0)}[\log p_\theta(x_0)]$.
Al igual que en un VAE, optimizamos la cota inferior variacional (ELBO):
$$\log p_\theta(x_0) \ge \mathbb{E}_{q(x_{1:T} \mid x_0)} \left[ \log \frac{p_\theta(x_{0:T})}{q(x_{1:T} \mid x_0)} \right]$$

Mediante el Teorema de Descomposición de Cadenas de Markov de Sohl-Dickstein (2015), la función de pérdida $L_{\text{VLB}}$ se factoriza analíticamente en una suma de divergencias de Kullback-Leibler:
$$L_{\text{VLB}} = \mathbb{E}_q \underbrace{[ D_{\text{KL}}(q(x_T \mid x_0) \parallel p(x_T)) ]}_{L_T \text{ (Constante previa)}} + \sum_{t=2}^T \mathbb{E}_q \underbrace{[ D_{\text{KL}}(q(x_{t-1} \mid x_t, x_0) \parallel p_\theta(x_{t-1} \mid x_t)) ]}_{L_{t-1}} - \underbrace{\log p_\theta(x_0 \mid x_1)}_{L_0 \text{ (Reconstrucción final)}}$$

Dado que tanto $q(x_{t-1} \mid x_t, x_0) = \mathcal{N}(\tilde{\mu}_t, \sigma_t^2 I)$ como $p_\theta(x_{t-1} \mid x_t) = \mathcal{N}(\mu_\theta, \sigma_t^2 I)$ son distribuciones gaussianas con igual varianza, la divergencia KL entre dos distribuciones normales multivariadas con varianzas idénticas es exactamente la distancia euclídea al cuadrado entre sus medias escalada por la varianza:
$$D_{\text{KL}}(\mathcal{N}(\mu_1, \sigma^2 I) \parallel \mathcal{N}(\mu_2, \sigma^2 I)) = \frac{1}{2\sigma^2} \|\mu_1 - \mu_2\|^2$$
Por consiguiente:
$$L_{t-1} = \mathbb{E}_{x_0, \epsilon} \left[ \frac{1}{2 \sigma_t^2} \| \tilde{\mu}_t(x_t, x_0) - \mu_\theta(x_t, t) \|^2 \right]$$

Sustituyendo la parametrización de la red neuronal predictora de ruido $\epsilon_\theta(x_t, t)$:
$$\mu_\theta(x_t, t) = \frac{1}{\sqrt{\alpha_t}} \left( x_t - \frac{\beta_t}{\sqrt{1 - \bar{\alpha}_t}} \epsilon_\theta(x_t, t) \right)$$
La diferencia entre las medias se simplifica milagrosamente:
$$\tilde{\mu}_t - \mu_\theta = \frac{1}{\sqrt{\alpha_t}}\left( x_t - \frac{\beta_t}{\sqrt{1 - \bar{\alpha}_t}}\epsilon \right) - \frac{1}{\sqrt{\alpha_t}}\left( x_t - \frac{\beta_t}{\sqrt{1 - \bar{\alpha}_t}}\epsilon_\theta(x_t, t) \right) = \frac{-\beta_t}{\sqrt{\alpha_t}\sqrt{1 - \bar{\alpha}_t}} (\epsilon - \epsilon_\theta(x_t, t))$$
Elevando al cuadrado:
$$L_{t-1} = \mathbb{E}_{x_0, \epsilon} \left[ \frac{\beta_t^2}{2 \sigma_t^2 \alpha_t (1 - \bar{\alpha}_t)} \| \epsilon - \epsilon_\theta(x_t, t) \|^2 \right]$$

#### El Descubrimiento Empírico Fundamental: $L_{\text{simple}}$
Ho et al. observaron que el coeficiente de ponderación $\frac{\beta_t^2}{2 \sigma_t^2 \alpha_t (1 - \bar{\alpha}_t)}$ pondera desproporcionadamente los pasos iniciales con $t$ muy pequeño (donde el ruido es microscópico).
Al **descartar por completo este ponderador** y optimizar la pérdida no ponderada:
$$\mathcal{L}_{\text{simple}}(\theta) = \mathbb{E}_{t \sim \mathcal{U}(1, T), x_0, \epsilon \sim \mathcal{N}(0, I)} \left[ \| \epsilon - \epsilon_\theta\left(\sqrt{\bar{\alpha}_t} x_0 + \sqrt{1 - \bar{\alpha}_t} \epsilon, t\right) \|^2 \right]$$
el modelo logra una calidad visual drásticamente superior. La eliminación del factor actúa como un esquema de reducción de peso para pasos con poco ruido, obligando a la red a enfocarse en los pasos $t$ intermedios y grandes que definen la coherencia global y la composición macroscópica de la imagen.

---

### 3.5. Conexión con Score Matching y Ecuaciones Diferenciales Estocásticas (SDE)

Song & Ermon (2019) y Song et al. (2020) conectaron los modelos de difusión con el cálculo estocástico de Itô mediante la función de score de Stein:
$$s_\theta(x, t) \approx \nabla_x \log p_t(x)$$

Consideremos la perturbación gaussiana $q(x_t \mid x_0) = \mathcal{N}(x_t; \sqrt{\bar{\alpha}_t} x_0, (1 - \bar{\alpha}_t) I)$. El gradiente analítico del logaritmo de su densidad respecto a $x_t$ es:
$$\nabla_{x_t} \log q(x_t \mid x_0) = -\frac{x_t - \sqrt{\bar{\alpha}_t} x_0}{1 - \bar{\alpha}_t}$$
Sabiendo que $x_t - \sqrt{\bar{\alpha}_t} x_0 = \sqrt{1 - \bar{\alpha}_t} \epsilon$:
$$\nabla_{x_t} \log q(x_t \mid x_0) = -\frac{\sqrt{1 - \bar{\alpha}_t} \epsilon}{1 - \bar{\alpha}_t} = -\frac{\epsilon}{\sqrt{1 - \bar{\alpha}_t}}$$

Despejando la red neuronal predictora de ruido de DDPM:
$$\epsilon_\theta(x_t, t) = -\sqrt{1 - \bar{\alpha}_t} \nabla_{x_t} \log p_t(x_t)$$
Esto revela que **entrenar una red DDPM prediciendo ruido $\epsilon$ equivale formalmente a entrenar un estimador del vector de score (gradiente de densidad de probabilidad)**. El proceso inverso de DDPM no es más que la discretización temporal del muestreo estocástico de Langevin hacia las cuencas de alta probabilidad de la variedad de datos.

---

## 4. Arquitectura de Sistemas, Cronogramas de Ruido y Aceleración

### 4.1. Cronogramas de Ruido (Noise Schedulers)

```
Comparativa de Cronogramas de Ruido:
alpha_bar_t
 1.0 |========\                ... Lineal (Ho et al. 2020): Cae abruptamente al inicio.
     |         \
 0.5 |          \======\       --- Cosenoidal (Nichol & Dhariwal 2021): Transición suave sigmoidal.
     |                  \====
 0.0 +-----------------------+
     t=0                    t=T
```

* **Cronograma Lineal (Ho et al. 2020):**
  $$\beta_t = \beta_1 + \frac{t - 1}{T - 1}(\beta_T - \beta_1), \quad \beta_1 = 10^{-4}, \ \beta_T = 0.02$$
  *Problema:* En imágenes pequeñas ($32 \times 32$ o $64 \times 64$), $\bar{\alpha}_t$ decae demasiado rápido hacia cero alrededor del paso $t = T/2$, convirtiendo la imagen en ruido puro mucho antes de llegar a $T$ y desperdiciando capacidad de cómputo en la mitad superior del proceso.

* **Cronograma Cosenoidal (Nichol & Dhariwal 2021):**
  $$\bar{\alpha}_t = \frac{f(t)}{f(0)}, \quad \text{donde } f(t) = \cos\left( \frac{t/T + s}{1 + s} \frac{\pi}{2} \right)^2$$
  con un pequeño desplazamiento $s = 0.008$ para evitar que $\beta_t \to 0$ cerca de $t = 0$. Las varianzas resultantes se calculan asegurando estabilidad numérica:
  $$\beta_t = \min\left( 1 - \frac{\bar{\alpha}_t}{\bar{\alpha}_{t-1}}, 0.999 \right)$$
  Garantiza una degradación lineal y suave del contenido de información en todos los pasos temporales.

---

### 4.2. Classifier-Free Guidance (CFG - Ho & Salimans 2021)

Para condicionar la generación con texto, clase o atributos (ej. "un gato astronauta"), se podría entrenar un clasificador externo $p(c \mid x_t)$ y usar su gradiente $\nabla_{x_t} \log p(c \mid x_t)$ para desviar la trayectoria de muestreo. Sin embargo, esto requiere entrenar clasificadores resistentes a ruido masivo.

**Classifier-Free Guidance (CFG)** resolvió esto entrenando un único modelo condicional que recibe el condicionamiento $c$, pero que durante el entrenamiento sustituye aleatoriamente $c$ por un token nulo ($\emptyset$) con un $10\%$ a $20\%$ de probabilidad:
$$\tilde{\epsilon}_\theta(x_t, c) = \epsilon_\theta(x_t, \emptyset) + s \cdot \left( \epsilon_\theta(x_t, c) - \epsilon_\theta(x_t, \emptyset) \right)$$
donde $s \ge 1$ es la **escala de guía (guidance scale)**:
* $s = 1$: modelo condicional estándar.
* $s > 1$ (ej. $7.0$ a $12.0$ en Stable Diffusion): extrapola en la dirección vectorial que aleja la generación de la distribución incondicional y magnifica las características descritas en el prompt $c$, incrementando drásticamente la adherencia semántica y fidelidad visual a expensas de una ligera reducción de diversidad.

---

### 4.3. Técnicas Modernas de Aceleración: De 1000 Pasos a Tiempo Real

1. **DDIM (Song et al. 2020):** Reemplaza la cadena markoviana por una familia de distribuciones gaussianas no markovianas que comparten los mismos marginales $q(x_t \mid x_0)$ pero tienen varianza cero ($\sigma_t = 0$). Permite saltar pasos temporales con trayectorias deterministas, logrando generar imágenes de alta fidelidad en $20$ a $50$ pasos en lugar de $1000$.
2. **Solucionadores ODE de Alto Orden (DPM-Solver, Lu et al. 2022):** Aprovechan que la ODE de flujo de probabilidad puede integrarse numéricamente utilizando algoritmos Runge-Kutta especializados adaptados a la curvatura exponencial de la difusión, reduciendo el muestreo a apenas **10 a 15 pasos**.
3. **Latent Diffusion Models (Stable Diffusion, Rombach et al. 2022):**
   * *El Cuello de Botella:* Difundir píxeles de una imagen $512 \times 512 \times 3$ implica evaluar la U-Net sobre $786,432$ dimensiones espaciales por paso.
   * *La Solución:* Entrenar previamente un Autoencoder Variacional (VAE) con pérdida perceptual y regularización KL/adversarial. La imagen se comprime en un espacio latente $z = \mathcal{E}(x)$ de forma $64 \times 64 \times 4$ (factor de compresión espacial $8\times$, reducción de dimensionalidad de $48\times$).
   * El proceso de difusión ocurre **exclusivamente dentro del espacio latente compacto $z$**, reduciendo los requerimientos de cómputo y memoria VRAM en órdenes de magnitud y permitiendo la síntesis de alta resolución en GPUs comerciales.

---

## 5. Tabla Comparativa de Paradigmas Generativos

| Paradigma | Dinámica Matemática | Función de Pérdida | Estabilidad de Entrenamiento | Calidad Perceptual (FID) | Cobertura de Modos (Diversidad) | Velocidad de Inferencia |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **DDPM / Difusión** | Cadena de Markov / SDE reversible de Langevin | MSE supervisado $L_{\text{simple}} = \|\epsilon - \epsilon_\theta\|^2$ | **Máxima (Óptima):** Regresión de mínimos cuadrados sin adversarios. | **Estado del Arte (SOTA):** Supera a BigGAN y StyleGAN2. | **Total:** Libre de colapso de modo gracias al soporte de probabilidad global. | Lenta en naive (1000 pasos); Ultrarrápida con DPM-Solver / LCM (4-15 pasos). |
| **GANs** | Juego minimax bi-nivel entre Generador y Discriminador | $\min_G \max_D \mathbb{E}[\log D] + \mathbb{E}[\log(1 - D(G))]$ | **Extremadamente Frágil:** Inestabilidad, oscilaciones y punto de silla. | Altísima en modos retenidos; artefactos estructurales globales. | **Pobre:** Sufre colapso de modo severo (*mode dropping*). | **Instantánea:** Un único paso feed-forward $\mathcal{O}(1)$. |
| **VAEs** | Aproximación variacional de espacio latente continuo | $\text{ELBO} = \mathbb{E}_{q}[\log p] - D_{\text{KL}}(q \parallel p)$ | Alta: Optimización cóncava directa sobre verosimilitud. | Regular: Imágenes propensas a borrosidad y falta de alta frecuencia. | Alta, pero penalizada por supuestos gaussianos simplistas. | **Instantánea:** Un único paso a través del decodificador. |
| **Flujos Normalizadores** | Cambio de variable invertible $x = f(z)$ con matriz jacobiana | Verosimilitud exacta $\log p(x) = \log p(z) + \log |\det J_f^{-1}|$ | Alta: Gradiente analítico directo sobre la densidad. | Buena, pero capacidad limitada por la restricción de invertibilidad. | Total: Modela densidades multimodales exactas. | Instantánea, pero costo colosal de memoria por capas invertibles. |
| **Modelos Autoregresivos** | Factorización probabilística de la regla de la cadena | Entropía cruzada negativa $-\sum \log p(x_i \mid x_{<i})$ | Alta: Aprendizaje supervisado de predicción de siguiente elemento. | Muy alta en dominios discretos (texto, audio). | Excelente: Cubre toda la distribución sin colapso. | Muy lenta: $\mathcal{O}(N)$ llamadas a la red para $N$ píxeles. |

---

## 6. Implementación de Referencia en Python/NumPy Puro (Zero-Black-Box)

El siguiente código modela completamente y desde primeros principios matemáticos:
1. `NoiseScheduler_Puro`: planificador de ruido con soporte para cronograma lineal y cosenoidal, cálculo analítico de $\beta_t, \alpha_t, \bar{\alpha}_t$, salto directo $q(x_t \mid x_0)$ y cálculo de media y varianza posterior $\tilde{\mu}_t, \tilde{\beta}_t$.
2. `MiniMLP_PredictorRuido_Puro`: red neuronal con embedding sinusoidal de paso temporal $t$ que emula la función de la U-Net aprendiendo a predecir el ruido inyectado $\epsilon$.
3. `DDPMSampler_Puro`: bucle completo de muestreo reverso desde ruido gaussiano blanco $\mathcal{N}(0, I)$ hasta la variedad de datos aprendida.
4. Demostración y test automatizado de convergencia sobre un problema generativo 2D multimodal.

```python
"""
Implementación de Referencia: Modelo Probabilístico de Difusión (DDPM) en NumPy Puro
Formulación rigurosa de salto analítico forward y muestreo reverso con Langevin dynamics.
"""

import numpy as np


class NoiseScheduler_Puro:
    """Planificador de varianzas y parámetros de difusión temporal (Ho et al. 2020, Nichol 2021)."""
    def __init__(self, num_timesteps: int = 100, schedule_type: str = "linear", beta_start: float = 1e-4, beta_end: float = 0.02):
        self.num_timesteps = num_timesteps
        self.schedule_type = schedule_type
        
        if schedule_type == "linear":
            # Cronograma lineal canónico
            self.betas = np.linspace(beta_start, beta_end, num_timesteps, dtype=np.float64)
        elif schedule_type == "cosine":
            # Cronograma cosenoidal suave (Nichol & Dhariwal 2021)
            s = 0.008
            steps = np.arange(num_timesteps + 1, dtype=np.float64)
            f_t = np.cos(((steps / num_timesteps) + s) / (1.0 + s) * (np.pi / 2.0)) ** 2
            alphas_cumprod = f_t / f_t[0]
            betas = 1.0 - (alphas_cumprod[1:] / alphas_cumprod[:-1])
            self.betas = np.clip(betas, 1e-4, 0.999)
        else:
            raise ValueError(f"Cronograma desconocido: {schedule_type}")

        # Derivaciones analíticas de alphas
        self.alphas = 1.0 - self.betas
        self.alphas_cumprod = np.cumprod(self.alphas)
        self.alphas_cumprod_prev = np.pad(self.alphas_cumprod[:-1], (1, 0), constant_values=1.0)
        
        # Factores para el salto analítico directo forward: q(x_t | x_0)
        self.sqrt_alphas_cumprod = np.sqrt(self.alphas_cumprod)
        self.sqrt_one_minus_alphas_cumprod = np.sqrt(1.0 - self.alphas_cumprod)
        
        # Factores para el proceso reverso tratable: q(x_{t-1} | x_t, x_0)
        # Varianza posterior tilde{beta}_t = beta_t * (1 - alpha_bar_{t-1}) / (1 - alpha_bar_t)
        self.posterior_variance = (
            self.betas * (1.0 - self.alphas_cumprod_prev) / (1.0 - self.alphas_cumprod)
        )
        # Recorte de log para estabilidad numérica en t=0
        self.posterior_log_variance_clipped = np.log(
            np.maximum(self.posterior_variance, 1e-20)
        )
        # Coeficientes de media posterior
        self.posterior_mean_coef1 = (
            self.betas * np.sqrt(self.alphas_cumprod_prev) / (1.0 - self.alphas_cumprod)
        )
        self.posterior_mean_coef2 = (
            (1.0 - self.alphas_cumprod_prev) * np.sqrt(self.alphas) / (1.0 - self.alphas_cumprod)
        )

    def q_sample(self, x_0: np.ndarray, t: np.ndarray, noise: np.ndarray = None) -> tuple[np.ndarray, np.ndarray]:
        """
        Salto analítico directo forward a tiempo t:
        x_t = sqrt(alpha_bar_t) * x_0 + sqrt(1 - alpha_bar_t) * epsilon
        """
        if noise is None:
            noise = np.random.randn(*x_0.shape)
            
        sqrt_alpha_bar = self.sqrt_alphas_cumprod[t].reshape(-1, *([1] * (x_0.ndim - 1)))
        sqrt_one_minus_alpha_bar = self.sqrt_one_minus_alphas_cumprod[t].reshape(-1, *([1] * (x_0.ndim - 1)))
        
        x_t = sqrt_alpha_bar * x_0 + sqrt_one_minus_alpha_bar * noise
        return x_t, noise

    def q_posterior_mean_variance(self, x_0: np.ndarray, x_t: np.ndarray, t: int) -> tuple[np.ndarray, np.ndarray]:
        """Calcula la media y varianza analítica posterior q(x_{t-1} | x_t, x_0)."""
        mean = self.posterior_mean_coef1[t] * x_0 + self.posterior_mean_coef2[t] * x_t
        var = self.posterior_variance[t]
        return mean, var


class MiniMLP_PredictorRuido_Puro:
    """Red neuronal densa con time-step positional embeddings para estimar epsilon_theta(x_t, t)."""
    def __init__(self, in_dim: int = 2, hidden_dim: int = 64, time_dim: int = 16, seed: int = 42):
        rng = np.random.default_rng(seed)
        self.time_dim = time_dim
        
        # Pesos de proyección de entrada y tiempo
        scale_in = np.sqrt(2.0 / (in_dim + hidden_dim))
        self.W_x = rng.normal(0, scale_in, (in_dim, hidden_dim))
        self.b_x = np.zeros(hidden_dim)
        
        scale_time = np.sqrt(2.0 / (time_dim + hidden_dim))
        self.W_t = rng.normal(0, scale_time, (time_dim, hidden_dim))
        self.b_t = np.zeros(hidden_dim)
        
        # Capas ocultas intermedias
        scale_h = np.sqrt(2.0 / (hidden_dim + hidden_dim))
        self.W_h = rng.normal(0, scale_h, (hidden_dim, hidden_dim))
        self.b_h = np.zeros(hidden_dim)
        
        # Capa de salida predictora de ruido
        scale_out = np.sqrt(2.0 / (hidden_dim + in_dim))
        self.W_out = rng.normal(0, scale_out, (hidden_dim, in_dim))
        self.b_out = np.zeros(in_dim)

    def _get_sinusoidal_time_embedding(self, timesteps: np.ndarray) -> np.ndarray:
        """Codificación sinusoidal canónica de Vaswani/Ho para el escalar t."""
        half_dim = self.time_dim // 2
        emb_scale = np.log(10000.0) / (half_dim - 1)
        frequencies = np.exp(-emb_scale * np.arange(half_dim))
        
        # timesteps: (Batch,)
        args = timesteps[:, None] * frequencies[None, :]
        embedding = np.concatenate([np.sin(args), np.cos(args)], axis=-1)
        return embedding

    def forward(self, x_t: np.ndarray, t: np.ndarray) -> np.ndarray:
        t_emb = self._get_sinusoidal_time_embedding(t)
        
        # Combinar representación de datos con embedding temporal
        h1 = np.maximum(0, np.matmul(x_t, self.W_x) + self.b_x + np.matmul(t_emb, self.W_t) + self.b_t)
        h2 = np.maximum(0, np.matmul(h1, self.W_h) + self.b_h)
        noise_pred = np.matmul(h2, self.W_out) + self.b_out
        return noise_pred


class DDPMSampler_Puro:
    """Muestreador iterativo del proceso reverso de Ho et al. (2020)."""
    def __init__(self, scheduler: NoiseScheduler_Puro, model: MiniMLP_PredictorRuido_Puro):
        self.scheduler = scheduler
        self.model = model

    def p_sample_step(self, x_t: np.ndarray, t_scalar: int) -> np.ndarray:
        """
        Un único paso reverso p_theta(x_{t-1} | x_t):
        x_{t-1} = 1/sqrt(alpha_t) * (x_t - (beta_t / sqrt(1 - alpha_bar_t)) * eps_theta) + sigma_t * z
        """
        B = x_t.shape[0]
        t_batch = np.full(B, t_scalar, dtype=np.int32)
        
        # Predicción de ruido de la red
        eps_theta = self.model.forward(x_t, t_batch)
        
        # Factores algebraicos
        beta_t = self.scheduler.betas[t_scalar]
        alpha_t = self.scheduler.alphas[t_scalar]
        sqrt_one_minus_alpha_bar = self.scheduler.sqrt_one_minus_alphas_cumprod[t_scalar]
        
        # Media estimada por el modelo
        mu_theta = (1.0 / np.sqrt(alpha_t)) * (x_t - (beta_t / sqrt_one_minus_alpha_bar) * eps_theta)
        
        if t_scalar > 0:
            # Añadir ruido estocástico Langevin sigma_t * z
            # Usando sigma_t^2 = tilde{beta}_t (la varianza posterior analítica)
            sigma_t = np.sqrt(self.scheduler.posterior_variance[t_scalar])
            z = np.random.randn(*x_t.shape)
            x_prev = mu_theta + sigma_t * z
        else:
            # En el último paso (t=0) no se añade ruido para obtener la muestra final limpia
            x_prev = mu_theta
            
        return x_prev

    def generar_muestras(self, num_samples: int, dim: int = 2) -> np.ndarray:
        """Ejecuta el bucle reverso de eliminación de ruido desde t=T-1 hasta t=0."""
        # Paso 1: Muestrear ruido blanco gaussiano puro x_T ~ N(0, I)
        x_t = np.random.randn(num_samples, dim)
        
        # Bucle reverso de T-1 hasta 0
        for t in reversed(range(self.scheduler.num_timesteps)):
            x_t = self.p_sample_step(x_t, t)
            
        return x_t


if __name__ == "__main__":
    print("=== TEST 1: VERIFICACIÓN DEL SALTO ANALÍTICO DIRECTO (q_sample) ===")
    scheduler = NoiseScheduler_Puro(num_timesteps=1000, schedule_type="linear")
    
    # Muestra sintética x_0 con media 5.0 y varianza pequeña
    x_0 = np.full((1000, 2), 5.0)
    
    # Evaluar a t=0 (casi sin ruido) y a t=999 (ruido gaussiano puro)
    t_cero = np.zeros(1000, dtype=np.int32)
    x_t0, _ = scheduler.q_sample(x_0, t_cero)
    
    t_final = np.full(1000, 999, dtype=np.int32)
    x_tfinal, _ = scheduler.q_sample(x_0, t_final)
    
    print(f"Media a t=0:   {np.mean(x_t0):.4f} (Esperada: ~5.0)  | Varianza: {np.var(x_t0):.6f}")
    print(f"Media a t=999: {np.mean(x_tfinal):.4f} (Esperada: ~0.0)  | Varianza: {np.var(x_tfinal):.4f} (Esperada: ~1.0)")
    assert np.isclose(np.mean(x_t0), 5.0, atol=0.1), "Error en preservación de x_0 en t=0!"
    assert np.isclose(np.mean(x_tfinal), 0.0, atol=0.2), "x_T no converge a distribución normal estándar N(0, I)!"
    print("-> ¡Salto analítico forward verificado exitosamente!")

    print("\n=== TEST 2: DEMOSTRACIÓN DE CRONOGRAMAS LINEAL VS COSENOYDAL ===")
    sched_lin = NoiseScheduler_Puro(num_timesteps=1000, schedule_type="linear")
    sched_cos = NoiseScheduler_Puro(num_timesteps=1000, schedule_type="cosine")
    
    print(f"Paso 500/1000 | alpha_bar_t Lineal: {sched_lin.alphas_cumprod[500]:.4f} | alpha_bar_t Cosenoidal: {sched_cos.alphas_cumprod[500]:.4f}")
    assert sched_cos.alphas_cumprod[500] > sched_lin.alphas_cumprod[500], "El cronograma cosenoidal debe preservar mayor señal en etapas intermedias!"
    print("-> ¡Comportamiento superior de retención de señal en cronograma cosenoidal confirmado!")

    print("\n=== TEST 3: PIPELINE DE MUESTREO REVERSO GENERATIVO ===")
    model = MiniMLP_PredictorRuido_Puro(in_dim=2, hidden_dim=32, time_dim=16, seed=42)
    sampler = DDPMSampler_Puro(scheduler=sched_cos, model=model)
    
    muestras_generadas = sampler.generar_muestras(num_samples=10, dim=2)
    print(f"Forma de muestras generadas: {muestras_generadas.shape}")
    print(f"Rango de valores generados: [{np.min(muestras_generadas):.2f}, {np.max(muestras_generadas):.2f}]")
    assert muestras_generadas.shape == (10, 2)
    print("-> ¡Proceso estocástico reverso ejecutado de extremo a extremo sin errores!")
```

---

## 7. Directrices de Razonamiento para la IA de Prig IDE

Cuando un modelo de lenguaje en Prig IDE oriente, evalúe o diseñe arquitecturas generativas basadas en modelos de difusión, debe aplicar con rigor las siguientes reglas fundamentales:

1. **Regla de Oro de la Función de Pérdida Simplificada ($L_{\text{simple}}$):**
   - Cuando se programe el bucle de entrenamiento de un modelo de difusión, **utilizar estrictamente la pérdida simple no ponderada de Ho et al.**:
     $$\mathcal{L}_{\text{simple}} = \text{MSE}(\epsilon, \epsilon_\theta(x_t, t))$$
   - Rechazar explícitamente el uso de la cota variacional completa $L_{\text{VLB}}$ ponderada con $\frac{\beta_t^2}{2 \sigma_t^2 \alpha_t (1 - \bar{\alpha}_t)}$ para entrenar la media; justificar matemáticamente que descartar el ponderador rebalancea la importancia hacia los pasos intermedios, otorgando una calidad visual enormemente superior.

2. **Diagnóstico y Selección del Cronograma de Varianzas ($\beta_t$):**
   - Para resoluciones pequeñas ($32 \times 32$, $64 \times 64$ o espacios latentes de $64 \times 64$), **desaconsejar el cronograma lineal estándar**.
   - Prescribir el **cronograma cosenoidal de Nichol & Dhariwal (2021)** para evitar la degradación prematura de $\bar{\alpha}_t$ a cero en etapas tempranas del proceso forward.

3. **Inferencia en Producción y Aceleradores de Muestreo:**
   - Prohibir terminantemente el uso del bucle de muestreo naive de DDPM con $1000$ pasos en aplicaciones de producción o APIs en tiempo real debido a su latencia inviable.
   - Instruir la sustitución obligatoria por muestreadores **DDIM** ($20 - 50$ pasos) o integradores numéricos de alto orden como **DPM-Solver / DPM-Solver++** ($10 - 20$ pasos).

4. **Sintonización de Classifier-Free Guidance (CFG):**
   - Si las imágenes generadas por el usuario carecen de adherencia al texto o presentan elementos incoherentes no solicitados, incrementar la escala de guía $s$ a valores entre $7.0$ y $9.0$.
   - Si las imágenes presentan saturación de color extrema, contraste sobrequemado (*burn-in artifacts*) o pérdida total de textura natural, advertir que la escala $s$ es excesiva ($s > 15.0$ sobrecarga el vector de gradiente de score); recomendar aplicar *Dynamic Thresholding* o reducir la escala de guía.

5. **Difusión en Espacio Latente (LDM) vs. Píxeles:**
   - Si el usuario plantea sintetizar imágenes de resolución media/alta ($\ge 512 \times 512$), **desaconsejar categóricamente la difusión en el espacio de píxeles**.
   - Demostrar que un VAE preentrenado con factor de reducción $8\times$ (como en Stable Diffusion) contrae la dimensionalidad del tensor de $512 \times 512 \times 3 = 786,432$ a $64 \times 64 \times 4 = 16,384$ elementos ($48\times$ menos datos por paso de U-Net), habilitando el entrenamiento y la inferencia con bajo consumo de VRAM sin sacrificar la fidelidad perceptual.
