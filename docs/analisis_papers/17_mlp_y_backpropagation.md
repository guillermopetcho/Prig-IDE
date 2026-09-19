# Monografía 17: Perceptrón Multicapa (MLP) y Backpropagation — De la Ruptura de Minsky al Teorema de Aproximación Universal, Modo Reverso y Optimizadores Modernos

> **Directorio de Ubicación:** `docs/analisis_papers/17_mlp_y_backpropagation.md`  
> **Ficha Técnica Modular Resumida:** [`docs/algoritmos_ml/17_mlp_y_backpropagation.md`](../algoritmos_ml/17_mlp_y_backpropagation.md)  
> **Estado del Documento:** Riguroso / Nivel Doctoral / Producción Académica  

---

## 1. Ficha Bibliográfica y Genealogía de Papers Seminales

1. **El Perceptrón Monocapa y la Ilusión Inicial (1958):**
   - **Título:** *The perceptron: a probabilistic model for information storage and organization in the brain*
   - **Autor:** Frank Rosenblatt (Cornell Aeronautical Laboratory).
   - **Publicación:** *Psychological Review*, 65(6), pp. 386–408 (1958).
   - **Aporte Principal:** Primera formulación matemática y computacional de un clasificador lineal adaptativo bio-inspirado, gobernado por la regla de corrección de pesos delta ante errores de clasificación binaria.

2. **La Paradoja de Minsky y el Invierno de la IA (MIT Press, 1969):**
   - **Título:** *Perceptrons: An Introduction to Computational Geometry*
   - **Autores:** Marvin Minsky y Seymour Papert.
   - **Publicación:** MIT Press, Cambridge, MA (1969; edición ampliada en 1987).
   - **Aporte Principal:** Demostración analítica de la limitación intrínseca del perceptrón lineal de Rosenblatt para separar funciones booleanas no linealmente separables (canónicamente el operador **XOR**). Demostraron que resolver problemas no lineales requería múltiples capas ocultas, pero conjeturaron erróneamente que entrenar tales redes multicapa sería computacionalmente inviable.

3. **El Paper Fundacional del Backpropagation Moderno (Nature, 1986):**
   - **Título:** *Learning representations by back-propagating errors*
   - **Autores:** David E. Rumelhart, Geoffrey E. Hinton y Ronald J. Williams.
   - **Publicación:** *Nature*, 323(6088), pp. 533–536 (1986).
   - **Aporte Principal:** Formalización del algoritmo de **Retropropagación del Error** (*Backpropagation*), aplicando la regla de la cadena multivariante en grafos computacionales acíclicos mediante diferenciación automática en modo reverso. Demostraron que las capas ocultas aprenden representaciones internas semánticas capaces de resolver problemas no lineales como XOR y codificación de familias lingüísticas.

4. **El Teorema de Aproximación Universal (1989, 1991):**
   - **Papers Seminales:**
     - George Cybenko (1989): *Approximation by superpositions of a sigmoidal function*. *Mathematics of Control, Signals, and Systems*, 2(4), pp. 303–314.
     - Kurt Hornik, Maxwell Stinchcombe y Halbert White (1989): *Multilayer feedforward networks are universal approximators*. *Neural Networks*, 2(5), pp. 359–366.
     - Kurt Hornik (1991): *Approximation capabilities of multilayer feedforward networks*. *Neural Networks*, 4(2), pp. 251–257.
   - **Aporte Principal:** Demostración matemática rigurosa de que cualquier función continua definida sobre un subconjunto compacto de $\mathbb{R}^D$ puede ser aproximada uniformemente con precisión arbitraria $\epsilon > 0$ mediante una red neuronal de alimentación directa (*feedforward*) de una única capa oculta con un número finito de neuronas y activaciones no lineales continuas.

5. **El Análisis de Varianza y la Inicialización de Pesos (2010, 2015):**
   - **Inicialización Glorot/Xavier (2010):** Xavier Glorot y Yoshua Bengio. *Understanding the difficulty of training deep feedforward neural networks*. *AISTATS 2010*, pp. 249–256.
   - **Inicialización He/Kaiming (2015):** Kaiming He, Xiangyu Zhang, Shaoqing Ren y Jian Sun. *Delving Deep into Rectifiers: Surpassing Human-Level Performance on ImageNet Classification*. *ICCV 2015*, pp. 1026–1034.
   - **Aporte Principal:** Estudio de la propagación de la varianza estadística de las activaciones y gradientes a través de capas profundas, erradicando el desvanecimiento y la explosión exponencial de gradientes mediante la calibración exacta de la escala aleatoria en función del número de conexiones entrantes ($n_{in}$) y salientes ($n_{out}$).

6. **La Desconexión del Decaimiento de Pesos: AdamW (ICLR, 2019):**
   - **Adam Original (2014):** Diederik P. Kingma y Jimmy Ba. *Adam: A Method for Stochastic Optimization*. *ICLR 2015* (arXiv:1412.6980).
   - **AdamW (2019):** Ilya Loshchilov y Frank Hutter. *Decoupled Weight Decay Regularization*. *ICLR 2019* (arXiv:1711.05101).
   - **Aporte Principal:** Demostración de que la regularización $L_2$ clásica se acopla patológicamente con los momentos de segundo orden en optimizadores adaptativos, subpenalizando gradientes grandes. Formulación de **AdamW**, que aplica el decaimiento de pesos de manera desacoplada de la actualización del momento adaptativo, convirtiéndose en el estándar universal de entrenamiento en Deep Learning.

---

## 2. Génesis Teórica: Superando el Límite de Minsky y el Teorema de Aproximación Universal

### 2.1. El Colapso del Perceptrón Monocapa: El Problema XOR

Sea un clasificador lineal definido por $y = \mathbb{I}(w_1 x_1 + w_2 x_2 + b \ge 0)$.  
Para modelar la función lógica **XOR** con las cuatro entradas booleanas posibles:
1. $(0, 0) \to 0 \implies b < 0$
2. $(1, 0) \to 1 \implies w_1 + b \ge 0$
3. $(0, 1) \to 1 \implies w_2 + b \ge 0$
4. $(1, 1) \to 0 \implies w_1 + w_2 + b < 0$

Sumando las desigualdades (2) y (3):
$$w_1 + w_2 + 2b \ge 0$$
Por la condición (1), $b < 0 \implies w_1 + w_2 + b > w_1 + w_2 + 2b \ge 0$.  
Esto implica que $w_1 + w_2 + b \ge 0$, lo cual entra en **contradicción matemática directa** con la condición (4) ($w_1 + w_2 + b < 0$).  
No existe ningún hiperplano lineal en $\mathbb{R}^2$ capaz de separar las clases del XOR.

```
       x₂ ▲                                        h₂ ▲
          │   (0, 1) [Clase 1]                        │   (1, 0) [Clase 1]
          │      ●                                    │      ●
          │                 (1, 1) [Clase 0]          │
          │                    ○                      │                 (0, 0) [Clase 0]
          │                                           │                    ○
          │   (0, 0) [Clase 0]                        │
          │      ○             ●  (1, 0) [Clase 1]    │   (0, 1) [Clase 1]
          └─────────────────────────────► x₁          └─────────────────────────────► h₁
             Espacio Original No Separable             Espacio Oculto Linealmente Separable
             por Hiperplano Rígido                    z = max(0, W x + b)
```

**La Solución Multicapa:**  
Introduciendo una capa intermedia oculta de dos neuronas no lineales $h = \phi(W^{(1)} x + b^{(1)})$, el espacio de entrada se proyecta no linealmente deformando la geometría euclidiana, de modo que las dos muestras de la Clase 1 se agrupan en una región colineal separable por un hiperplano lineal terminal $W^{(2)} h + b^{(2)} = 0$.

### 2.2. El Teorema de Aproximación Universal (Cybenko 1989, Hornik 1991)

#### Teorema:
Sea $I_D \subset \mathbb{R}^D$ un subconjunto compacto (cerrado y acotado), y sea $C(I_D)$ el espacio de Banach de funciones continuas reales sobre $I_D$ equipado con la norma del supremo $\|f\|_\infty = \sup_{x \in I_D} |f(x)|$.  
Sea $\sigma: \mathbb{R} \to \mathbb{R}$ cualquier función de activación continua, no constante y acotada (por ejemplo, sigmoide logística).  
Entonces, el conjunto de funciones representables por redes feedforward de una única capa oculta:
$$\mathcal{M}(\sigma) = \left\{ F(x) = \sum_{i=1}^M v_i \sigma(w_i^T x + b_i) \;\middle|\; M \in \mathbb{N}, \; v_i, b_i \in \mathbb{R}, \; w_i \in \mathbb{R}^D \right\}$$
es **denso en $C(I_D)$**.  
Es decir, para toda función objetivo $f \in C(I_D)$ y para cualquier tolerancia $\epsilon > 0$, existe un entero $M$ y un conjunto de parámetros $\{v_i, w_i, b_i\}$ tales que:
$$\sup_{x \in I_D} |f(x) - F(x)| < \epsilon$$

#### Demostración Esquemática (Vía Teorema de Hahn-Banach y Riesz):
1. Por el Teorema de Hahn-Banach, $\mathcal{M}(\sigma)$ es denso en $C(I_D)$ si y solo si la única medida de Borel regular con signo $\mu \in \mathcal{M}(I_D)$ que anula a todas las funciones de $\mathcal{M}(\sigma)$ es la medida nula $\mu = 0$:
   $$\int_{I_D} \sigma(w^T x + b) \, d\mu(x) = 0, \quad \forall w \in \mathbb{R}^D, \; b \in \mathbb{R} \implies \mu = 0$$
2. Dado que $\sigma$ es discriminatoria (ninguna combinación lineal no trivial se anula para todo $w$ y $b$), la convolución de $\sigma$ con la medida $\mu$ genera la transformada de Fourier de $\mu$.
3. Si la transformada de Fourier se anula en todo punto del espacio dual $\mathbb{R}^D$, por el Teorema de Inversión de Fourier la medida $\mu$ debe ser idénticamente cero, completando la demostración de densidad.

> **Importancia y Advertencia Técnica:**  
> El Teorema de Aproximación Universal demuestra la **capacidad representacional (expresividad)** de una red neuronal profunda, pero:
> 1. No proporciona un algoritmo para encontrar dichos pesos (el espacio de optimización es no convexo y NP-Hard en general).
> 2. Una capa oculta puede requerir un número astronómico de neuronas ($M \sim \mathcal{O}(2^D)$), mientras que las arquitecturas profundas (*Deep Networks*) parametrizan variedades complejas con un número exponencialmente menor de parámetros mediante composición jerárquica de funciones.
> 3. No garantiza generalización sobre datos no vistos fuera del compacto $I_D$.

---

## 3. Derivaciones Matemáticas Paso a Paso

### 3.1. Propagación Hacia Adelante Matricial (Forward Pass)

Consideremos una red de $L$ capas procesando simultáneamente un mini-lote de $B$ muestras:
$$X \in \mathbb{R}^{n_0 \times B}, \quad \text{donde } n_0 = D$$
Para cada capa $l = 1, 2, \dots, L$:
$$Z^{[l]} = W^{[l]} A^{[l-1]} + b^{[l]} \mathbf{1}_B^T \in \mathbb{R}^{n_l \times B}$$
$$A^{[l]} = \phi^{[l]}\left(Z^{[l]}\right) \in \mathbb{R}^{n_l \times B}$$
donde:
- $W^{[l]} \in \mathbb{R}^{n_l \times n_{l-1}}$ es la matriz de pesos sinápticos.
- $b^{[l]} \in \mathbb{R}^{n_l \times 1}$ es el vector de sesgos (*biases*).
- $\mathbf{1}_B = (1, 1, \dots, 1)^T \in \mathbb{R}^B$ efectúa la difusión (*broadcasting*) sobre el lote.
- $A^{[0]} = X$ es la entrada.
- $\phi^{[l]}$ es la función de activación no lineal evaluada elemento a elemento.

---

### 3.2. Derivación Rigurosa de Backpropagation (Diferenciación Automática en Modo Reverso)

Sea $\mathcal{L}$ la función de pérdida escalar promediada sobre el lote de tamaño $B$.  
Definimos el **vector de sensibilidad de error** en la capa $l$ como la derivada parcial respecto a la entrada pre-activada $Z^{[l]}$:
$$\delta^{[l]} \equiv \frac{\partial \mathcal{L}}{\partial Z^{[l]}} \in \mathbb{R}^{n_l \times B}$$

#### 1. Caso Base: Capa de Salida Terminal $L$ con Entropía Cruzada y Softmax
En clasificación multiclase con $C$ categorías, la capa terminal utiliza la función Softmax:
$$a_k^{[L]} = \frac{e^{z_k^{[L]}}}{\sum_{c=1}^C e^{z_c^{[L]}}}, \quad \forall k \in \{1, \dots, C\}$$
La función de pérdida de Entropía Cruzada (*Categorical Cross-Entropy*) para una muestra es:
$$\mathcal{L} = - \sum_{c=1}^C y_c \ln a_c^{[L]}$$
donde $y \in \{0, 1\}^C$ es el vector codificado en One-Hot.

Calculamos la derivada jacobiana de la función Softmax: $\frac{\partial a_c^{[L]}}{\partial z_k^{[L]}}$.  
Aplicando la regla del cociente:
- **Si $c = k$:**
  $$\frac{\partial a_k^{[L]}}{\partial z_k^{[L]}} = \frac{e^{z_k} \sum_j e^{z_j} - (e^{z_k})^2}{\left(\sum_j e^{z_j}\right)^2} = a_k^{[L]} - (a_k^{[L]})^2 = a_k^{[L]}(1 - a_k^{[L]})$$
- **Si $c \ne k$:**
  $$\frac{\partial a_c^{[L]}}{\partial z_k^{[L]}} = \frac{0 - e^{z_c} e^{z_k}}{\left(\sum_j e^{z_j}\right)^2} = - a_c^{[L]} a_k^{[L]}$$
En notación delta de Kronecker:
$$\frac{\partial a_c^{[L]}}{\partial z_k^{[L]}} = a_c^{[L]}(\delta_{ck} - a_k^{[L]})$$

Aplicando la regla de la cadena para obtener $\delta_k^{[L]} = \frac{\partial \mathcal{L}}{\partial z_k^{[L]}}$:
$$\delta_k^{[L]} = \sum_{c=1}^C \frac{\partial \mathcal{L}}{\partial a_c^{[L]}} \frac{\partial a_c^{[L]}}{\partial z_k^{[L]}} = \sum_{c=1}^C \left( -\frac{y_c}{a_c^{[L]}} \right) \left[ a_c^{[L]}(\delta_{ck} - a_k^{[L]}) \right]$$
Los términos $a_c^{[L]}$ se cancelan limpiamente:
$$\delta_k^{[L]} = - \sum_{c=1}^C y_c (\delta_{ck} - a_k^{[L]}) = - y_k (1) + a_k^{[L]} \sum_{c=1}^C y_c$$
Dado que $y$ es una distribución One-Hot, $\sum_{c=1}^C y_c = 1$.  
Por consiguiente, la complejidad del gradiente colapsa a la hermosura analítica:
$$\delta_k^{[L]} = a_k^{[L]} - y_k \implies \delta^{[L]} = A^{[L]} - Y$$

#### 2. Paso Inductivo: Retropropagación Hacia Capas Ocultas ($l < L$)
Deseamos calcular $\delta^{[l]} = \frac{\partial \mathcal{L}}{\partial Z^{[l]}}$ conociendo el tensor de error de la capa subsecuente $\delta^{[l+1]} = \frac{\partial \mathcal{L}}{\partial Z^{[l+1]}}$.  
Por la regla de la cadena multivariante:
$$\frac{\partial \mathcal{L}}{\partial z_i^{[l]}} = \sum_{j=1}^{n_{l+1}} \frac{\partial \mathcal{L}}{\partial z_j^{[l+1]}} \frac{\partial z_j^{[l+1]}}{\partial a_i^{[l]}} \frac{\partial a_i^{[l]}}{\partial z_i^{[l]}}$$
Evaluamos cada derivada parcial elemental:
1. $\frac{\partial \mathcal{L}}{\partial z_j^{[l+1]}} = \delta_j^{[l+1]}$ (por definición inductiva).
2. Dado que $z_j^{[l+1]} = \sum_k W_{jk}^{[l+1]} a_k^{[l]} + b_j^{[l+1]}$:
   $$\frac{\partial z_j^{[l+1]}}{\partial a_i^{[l]}} = W_{ji}^{[l+1]}$$
3. Dado que $a_i^{[l]} = \phi^{[l]}(z_i^{[l]})$:
   $$\frac{\partial a_i^{[l]}}{\partial z_i^{[l]}} = (\phi^{[l]})'(z_i^{[l]})$$
Sustituyendo:
$$\delta_i^{[l]} = \left[ \sum_{j=1}^{n_{l+1}} W_{ji}^{[l+1]} \delta_j^{[l+1]} \right] (\phi^{[l]})'(z_i^{[l]})$$
Expresado en álgebra matricial compacta:
$$\delta^{[l]} = \left( (W^{[l+1]})^T \delta^{[l+1]} \right) \odot (\phi^{[l]})'\left(Z^{[l]}\right)$$
donde $\odot$ denota el producto de Hadamard (multiplicación elemento a elemento).

#### 3. Cálculo de Gradientes Respecto a Pesos y Sesgos
Aplicando la regla de la cadena sobre los parámetros $W^{[l]}$ y $b^{[l]}$ promediando sobre el mini-lote de tamaño $B$:
$$\frac{\partial \mathcal{L}}{\partial W^{[l]}} = \frac{1}{B} \delta^{[l]} (A^{[l-1]})^T \in \mathbb{R}^{n_l \times n_{l-1}}$$
$$\frac{\partial \mathcal{L}}{\partial b^{[l]}} = \frac{1}{B} \delta^{[l]} \mathbf{1}_B = \frac{1}{B} \sum_{i=1}^B \delta_{*, i}^{[l]} \in \mathbb{R}^{n_l \times 1}$$

---

### 3.3. Análisis de Varianza y Derivación de Inicializaciones (Glorot y He)

Consideremos una capa lineal $z_i = \sum_{j=1}^{n_{in}} w_{ij} x_j$.  
Asumiendo que las entradas $x_j$ y los pesos $w_{ij}$ son variables aleatorias independientes e idénticamente distribuidas con media cero:
$$\mathbb{E}[z_i] = 0$$
$$\text{Var}(z_i) = \text{Var}\left( \sum_{j=1}^{n_{in}} w_{ij} x_j \right) = \sum_{j=1}^{n_{in}} \text{Var}(w_{ij} x_j)$$
Por la identidad de varianza de productos de variables independientes con media nula ($\text{Var}(A B) = \text{Var}(A) \text{Var}(B)$):
$$\text{Var}(z_i) = n_{in} \text{Var}(w) \text{Var}(x)$$

#### Inicialización Xavier / Glorot (2010)
Para funciones de activación lineales o simétricas alrededor de cero ($\tanh$ o sigmoide en su régimen lineal), la derivada en el origen es $\phi'(0) \approx 1$.  
Para evitar que la varianza explote o decaiga exponencialmente a través de $L$ capas:
- En el Forward Pass: requerimos $\text{Var}(z^{[l]}) = \text{Var}(z^{[l-1]}) \implies n_{in} \text{Var}(w) = 1 \implies \text{Var}(w) = \frac{1}{n_{in}}$.
- En el Backward Pass: el flujo de gradientes requiere $n_{out} \text{Var}(w) = 1 \implies \text{Var}(w) = \frac{1}{n_{out}}$.
Conciliando ambos requerimientos mediante su media armónica:
$$\text{Var}(W) = \frac{2}{n_{in} + n_{out}} \implies W \sim \mathcal{N}\left(0, \frac{2}{n_{in} + n_{out}}\right)$$

#### Inicialización Kaiming / He (2015)
Para la activación **ReLU** ($\phi(z) = \max(0, z)$), la mitad exacta de las activaciones se apagan a cero asumiendo una distribución simétrica sobre $z$.  
Por lo tanto:
$$\mathbb{E}[\phi(z)^2] = \frac{1}{2} \text{Var}(z)$$
Sustituyendo en la ecuación de varianza:
$$\text{Var}(a^{[l]}) = \frac{1}{2} n_{in} \text{Var}(w) \text{Var}(a^{[l-1]})$$
Para garantizar que $\text{Var}(a^{[l]}) = \text{Var}(a^{[l-1]})$, el factor multiplicativo debe ser exactamente igual a 1:
$$\frac{1}{2} n_{in} \text{Var}(w) = 1 \implies \text{Var}(W) = \frac{2}{n_{in}}$$
De esta deducción matemática nace la regla canónica de **He Normal**:
$$W \sim \mathcal{N}\left(0, \frac{2}{n_{in}}\right)$$

---

### 3.4. La Ruptura de AdamW (Loshchilov & Hutter 2019)

El optimizador **Adam** estándar (Kingma & Ba 2014) mantiene medias móviles exponenciales de los gradientes de primer orden (momento) y segundo orden (varianza no centrada):
$$m_t = \beta_1 m_{t-1} + (1 - \beta_1) g_t, \quad v_t = \beta_2 v_{t-1} + (1 - \beta_2) g_t^2$$
con corrección de sesgo para inicializaciones en cero:
$$\hat{m}_t = \frac{m_t}{1 - \beta_1^t}, \quad \hat{v}_t = \frac{v_t}{1 - \beta_2^t}$$

#### La Falla de la Regularización $L_2$ Clásica en Adam
En optimización tradicional, la regularización $L_2$ se implementa añadiendo $\frac{1}{2} \lambda \|\theta\|_2^2$ a la función de pérdida.  
Su gradiente modificado es $g_t^{\text{reg}} = g_t + \lambda \theta_{t-1}$.  
Al inyectar este gradiente en Adam:
$$\theta_t = \theta_{t-1} - \eta \frac{\hat{m}_t^{\text{reg}}}{\sqrt{\hat{v}_t^{\text{reg}}} + \epsilon}$$

**El Defecto Analítico:**  
Obsérvese que el término regularizador $\lambda \theta$ queda atrapado dentro de $v_t$, elevándose al cuadrado en el denominador.  
Para parámetros con gradientes históricos muy grandes, $\sqrt{\hat{v}_t} \gg 1$, lo que provoca que **el efecto efectivo del decaimiento de pesos sea suprimido y dividido por el gradiente acumulado**, impidiendo regularizar adecuadamente las conexiones dominantes.

#### La Solución AdamW: Decaimiento de Pesos Desacoplado
Loshchilov & Hutter proponen aplicar el decaimiento de pesos por fuera del momento adaptativo:
$$\theta_t = \theta_{t-1} - \eta \left( \frac{\hat{m}_t}{\sqrt{\hat{v}_t} + \epsilon} \right) - \eta \lambda \theta_{t-1}$$
donde $m_t$ y $v_t$ se calculan **estrictamente sobre el gradiente de pérdida puro $g_t$**.  
Esta formulación restaura la equivalencia matemática entre decaimiento de pesos y regularización de Tikhonov con tasa constante $\eta \lambda$, logrando una generalización sustancialmente superior en transformers y redes profundas.

---

## 4. Arquitectura de Sistemas y Regularización

```
Entrada X ──► [ Linear W¹, b¹ ] ──► [ BatchNorm ] ──► [ ReLU / GELU ] ──► [ Dropout (p) ] ──► Salida A¹
                    │
                    └─► Backward: Gradientes propagados vía regla de la cadena reversa (δ)
```

1. **Inverted Dropout (Srivastava et al. 2014):**
   - Durante el entrenamiento, cada neurona se multiplica por una máscara Bernoulli $m \sim \text{Bernoulli}(1 - p)$ y se divide inmediatamente por $(1 - p)$.
   - Esta escala anticipada hace que $\mathbb{E}[a_{\text{drop}}] = a$, eliminando cualquier cálculo de escalado en tiempo de inferencia y permitiendo que la fase de evaluación sea puramente determinista.

2. **Batch Normalization (Ioffe & Szegedy 2015):**
   - Normaliza cada dimensión de activación en el mini-lote a media cero y varianza unitaria:
     $$\hat{z}_i = \frac{z_i - \mu_B}{\sqrt{\sigma_B^2 + \epsilon}}, \quad y_i = \gamma \hat{z}_i + \beta$$
   - Como demostraron Santurkar et al. (2018), su verdadero impacto radica en suavizar la superficie de pérdida (haciendo el paisaje fuertemente Lipschitziano), lo que estabiliza el condicionamiento de la Hessiana y permite tasas de aprendizaje un orden de magnitud mayores.

3. **La Patología de Dying ReLU:**
   - Si una neurona cae en una región donde $z \le 0$ para todo el dataset de entrenamiento, $\phi'(z) = 0$.
   - En consecuencia, el gradiente hacia atrás $\delta$ se anula irreversiblemente y los pesos $W$ dejan de actualizarse para siempre.
   - Soluciones arquitectónicas: **LeakyReLU** ($\phi(z) = \max(\alpha z, z)$ con $\alpha \approx 0.01$), **ELU**, o **GELU** ($z \Phi(z)$) que proveen gradientes no nulos en el semiplano negativo.

---

## 5. Tabla Comparativa de Optimizadores

| Optimizador | Ecuación de Actualización | Adaptabilidad | Decaimiento de Pesos ($L_2$) | Adecuación Típica |
|---|---|---|---|---|
| **SGD** | $\theta \leftarrow \theta - \eta g_t$ | Fija para todos los pesos | Correcto ($\ell_2 \iff$ Weight Decay) | Convexo, problemas pequeños |
| **SGD + Momentum** | $v \leftarrow \mu v + g_t; \; \theta \leftarrow \theta - \eta v$ | Inercia direccional | Correcto | Visión por Computadora (ResNet) |
| **RMSprop** | $\theta \leftarrow \theta - \frac{\eta}{\sqrt{v_t} + \epsilon} g_t$ | Por coordenada ($1/\sqrt{\text{RMS}}$) | Acoplado patológico | Modelos recurrentes (RNN/LSTM) |
| **Adam** | $\theta \leftarrow \theta - \frac{\eta}{\sqrt{\hat{v}_t} + \epsilon} \hat{m}_t$ | Momentos de 1º y 2º orden | Acoplado patológico | Prototipado general |
| **AdamW** | $\theta \leftarrow \theta - \frac{\eta}{\sqrt{\hat{v}_t} + \epsilon} \hat{m}_t - \eta \lambda \theta$ | Momentos + Decaimiento desacoplado | **Matemáticamente estricto y desacoplado** | **Transformers, LLMs, Deep MLP** |

---

## 6. Implementación Pura en Python y NumPy (Sin PyTorch ni TensorFlow)

A continuación se presenta la implementación completa, vectorizada y modular de un **Perceptrón Multicapa (MLP)** de arquitectura profunda con inicialización He, activaciones ReLU y Softmax, retropropagación vectorial y el optimizador **AdamW Puro** con decaimiento desacoplado.

```python
import numpy as np


class MLP_Puro:
    """
    Implementación rigurosa de Perceptrón Multicapa (MLP) en NumPy puro.
    Incluye:
    - Inicialización He/Kaiming Normal.
    - Propagación directa matricial (Forward Pass).
    - Propagación retrógrada exacta (Backward Pass / Backpropagation).
    - Optimizador AdamW con decaimiento de pesos desacoplado.
    - Soporte para Inverted Dropout.
    """
    def __init__(self, layer_dims, dropout_rate=0.0, lr=1e-3, 
                 weight_decay=1e-2, beta1=0.9, beta2=0.999, eps=1e-8, random_state=42):
        self.layer_dims = layer_dims        # Lista de dimensiones: [n_in, n_h1, ..., n_out]
        self.dropout_rate = dropout_rate
        self.lr = lr
        self.weight_decay = weight_decay
        self.beta1 = beta1
        self.beta2 = beta2
        self.eps = eps
        self.random_state = random_state
        
        self.num_layers = len(layer_dims) - 1
        self.weights = {}
        self.biases = {}
        
        # Estados del optimizador AdamW
        self.m_w, self.v_w = {}, {}
        self.m_b, self.v_b = {}, {}
        self.t = 0

        self._inicializar_pesos()

    def _inicializar_pesos(self):
        """Inicialización He/Kaiming Normal: Var(W) = 2 / n_in."""
        rng = np.random.RandomState(self.random_state)
        for l in range(1, self.num_layers + 1):
            n_in = self.layer_dims[l - 1]
            n_out = self.layer_dims[l]
            # He Normal para capas intermedias ReLU y Xavier para terminal
            std = np.sqrt(2.0 / n_in) if l < self.num_layers else np.sqrt(2.0 / (n_in + n_out))
            self.weights[l] = rng.normal(0.0, std, size=(n_out, n_in))
            self.biases[l] = np.zeros((n_out, 1))

            # Inicializar momentos de AdamW a cero
            self.m_w[l] = np.zeros_like(self.weights[l])
            self.v_w[l] = np.zeros_like(self.weights[l])
            self.m_b[l] = np.zeros_like(self.biases[l])
            self.v_b[l] = np.zeros_like(self.biases[l])

    def _relu(self, Z):
        return np.maximum(0.0, Z)

    def _relu_derivada(self, Z):
        return (Z > 0.0).astype(np.float64)

    def _softmax(self, Z):
        """Softmax numéricamente estable con resta del máximo local."""
        max_Z = np.max(Z, axis=0, keepdims=True)
        exp_Z = np.exp(Z - max_Z)
        return exp_Z / np.sum(exp_Z, axis=0, keepdims=True)

    def forward(self, X, training=True):
        """
        Propagación hacia adelante matricial.
        X shape: (n_in, Batch_size).
        Retorna la salida Softmax A^[L] y el diccionario de activaciones en caché.
        """
        cache = {'A0': X}
        A = X

        for l in range(1, self.num_layers):
            Z = np.dot(self.weights[l], A) + self.biases[l]
            A = self._relu(Z)
            
            # Inverted Dropout
            if training and self.dropout_rate > 0.0:
                mask = (np.random.rand(*A.shape) >= self.dropout_rate) / (1.0 - self.dropout_rate)
                A = A * mask
                cache[f'M{l}'] = mask

            cache[f'Z{l}'] = Z
            cache[f'A{l}'] = A

        # Capa terminal L con activación Softmax
        ZL = np.dot(self.weights[self.num_layers], A) + self.biases[self.num_layers]
        AL = self._softmax(ZL)
        cache[f'Z{self.num_layers}'] = ZL
        cache[f'A{self.num_layers}'] = AL

        return AL, cache

    def backward(self, Y, cache):
        """
        Propagación retrógrada del error (Backpropagation).
        Y shape: (n_out, Batch_size) codificado en One-Hot.
        Calcula dW y db para cada capa mediante la regla de la cadena multivariante.
        """
        grads = {}
        B = Y.shape[1]  # Tamaño del lote

        # 1. Error en capa de salida terminal: delta^[L] = A^[L] - Y
        AL = cache[f'A{self.num_layers}']
        delta = AL - Y

        grads[f'dW{self.num_layers}'] = (1.0 / B) * np.dot(delta, cache[f'A{self.num_layers - 1}'].T)
        grads[f'db{self.num_layers}'] = (1.0 / B) * np.sum(delta, axis=1, keepdims=True)

        # 2. Retropropagación hacia atrás a través de las capas ocultas
        for l in range(self.num_layers - 1, 0, -1):
            # Propagar delta: ((W^[l+1])^T delta^[l+1]) * relu'(Z^[l])
            W_siguiente = self.weights[l + 1]
            delta = np.dot(W_siguiente.T, delta) * self._relu_derivada(cache[f'Z{l}'])
            
            # Retropropagar máscara de dropout si estuvo activa
            if f'M{l}' in cache:
                delta = delta * cache[f'M{l}']

            grads[f'dW{l}'] = (1.0 / B) * np.dot(delta, cache[f'A{l - 1}'].T)
            grads[f'db{l}'] = (1.0 / B) * np.sum(delta, axis=1, keepdims=True)

        return grads

    def step_adamw(self, grads):
        """Actualización de parámetros aplicando el algoritmo AdamW (Weight Decay desacoplado)."""
        self.t += 1
        for l in range(1, self.num_layers + 1):
            g_w = grads[f'dW{l}']
            g_b = grads[f'db{l}']

            # Actualización de momentos de pesos W
            self.m_w[l] = self.beta1 * self.m_w[l] + (1.0 - self.beta1) * g_w
            self.v_w[l] = self.beta2 * self.v_w[l] + (1.0 - self.beta2) * (g_w**2)

            m_w_hat = self.m_w[l] / (1.0 - self.beta1**self.t)
            v_w_hat = self.v_w[l] / (1.0 - self.beta2**self.t)

            # Decaimiento de pesos desacoplado: - lr * lambda * W
            actualizacion_w = m_w_hat / (np.sqrt(v_w_hat) + self.eps)
            self.weights[l] -= self.lr * actualizacion_w + self.lr * self.weight_decay * self.weights[l]

            # Actualización de sesgos b (sin regularización de decaimiento)
            self.m_b[l] = self.beta1 * self.m_b[l] + (1.0 - self.beta1) * g_b
            self.v_b[l] = self.beta2 * self.v_b[l] + (1.0 - self.beta2) * (g_b**2)

            m_b_hat = self.m_b[l] / (1.0 - self.beta1**self.t)
            v_b_hat = self.v_b[l] / (1.0 - self.beta2**self.t)

            self.biases[l] -= self.lr * (m_b_hat / (np.sqrt(v_b_hat) + self.eps))

    def fit(self, X, y_onehot, epochs=200):
        """Entrena la red mediante épocas completas registrando la pérdida de Cross-Entropy."""
        historial_loss = []
        B = X.shape[1]
        for ep in range(epochs):
            AL, cache = self.forward(X, training=True)
            # Pérdida de entropía cruzada
            loss = - (1.0 / B) * np.sum(y_onehot * np.log(np.maximum(AL, 1e-15)))
            historial_loss.append(loss)

            grads = self.backward(y_onehot, cache)
            self.step_adamw(grads)

        return historial_loss

    def predict(self, X):
        """Inferencia determinista (sin dropout). Retorna clases predichas."""
        AL, _ = self.forward(X, training=False)
        return np.argmax(AL, axis=0)


# =====================================================================
# Verificación Numérica: Solución al Problema No Lineal XOR
# =====================================================================
if __name__ == "__main__":
    np.random.seed(42)

    # Dataset Canónico XOR: 4 muestras, 2 variables de entrada
    X_xor = np.array([[0, 0],
                      [0, 1],
                      [1, 0],
                      [1, 1]], dtype=np.float64).T  # Shape: (2, 4)

    # Etiquetas de clase: 0 para (0,0) y (1,1); 1 para (0,1) y (1,0)
    y_xor = np.array([0, 1, 1, 0])
    Y_onehot = np.zeros((2, 4))
    for i, label in enumerate(y_xor):
        Y_onehot[label, i] = 1.0

    print("=== Validación Numérica: MLP Puro y Backpropagation en Problema XOR ===")
    print(f"Dimensiones de entrada: {X_xor.shape}, Etiquetas: {y_xor}")

    # Red con 1 capa oculta de 8 neuronas ReLU y salida Softmax
    red = MLP_Puro(layer_dims=[2, 8, 2], dropout_rate=0.0, lr=0.05, weight_decay=1e-4, random_state=42)
    historial = red.fit(X_xor, Y_onehot, epochs=250)

    predicciones = red.predict(X_xor)
    probabilidades, _ = red.forward(X_xor, training=False)

    print(f"Pérdida inicial: {historial[0]:.4f} -> Pérdida final tras 250 épocas: {historial[-1]:.4f}")
    print(f"Predicciones del modelo: {predicciones}")
    print(f"Valores reales esperados: {y_xor}")
    print(f"Exactitud alcanzada: {np.mean(predicciones == y_xor) * 100:.1f}%")
    print(f"Probabilidades asignadas por clase:\n{probabilidades.T}")
```

---

## 7. Directrices de Razonamiento para los Modelos de Inteligencia Artificial en Prig IDE

Cuando un modelo de lenguaje en Prig IDE diseñe, audite, optimice o depure arquitecturas basadas en **Perceptrón Multicapa (MLP)** (`torch.nn.Sequential`, `nn.Linear`, `tf.keras.layers.Dense`), aplicará de manera obligatoria la siguiente jerarquía de decisiones técnicas:

1. **Protocolo Estricto de Inicialización de Pesos:**
   - Si la red utiliza activaciones **ReLU, LeakyReLU o GELU**, prescribir **He / Kaiming Normal** (`torch.nn.init.kaiming_normal_`). Prohibir la inicialización estándar normal o uniforme sin escalar, pues provocará desvanecimiento de activaciones en capas intermedias.
   - Si se emplean activaciones sigmoideas o tangentes hiperbólicas en capas lineales, emplear **Glorot / Xavier Uniform/Normal** (`torch.nn.init.xavier_normal_`).

2. **Selección del Optimizador: Priorizar AdamW:**
   - Recomendar siempre **AdamW** sobre Adam clásico cuando se aplique regularización de decaimiento de pesos (`weight_decay > 0`). Explicar al usuario que Adam desacopla deficientemente el decaimiento de pesos penalizando de forma asimétrica a los parámetros con gradientes grandes.
   - Mantener tasas de aprendizaje típicas en el rango $[10^{-4}, 3 \times 10^{-3}]$ con planificador de decaimiento por coseno (*Cosine Annealing Schedule*).

3. **Diagnóstico del Fenómeno de Gradientes Anómalos:**
   - **Gradientes Explosivos (`Loss: NaN / Inf`):**
     - Activar inmediatamente **Recorte de Gradientes** (*Gradient Norm Clipping*): `torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)`.
     - Verificar que las entradas estén normalizadas con `StandardScaler` o `LayerNorm`.
   - **Gradientes Desvanecientes / Neuronas Muertas (Dying ReLU):**
     - Si la pérdida se estanca tempranamente, verificar el porcentaje de neuronas cuya activación es idénticamente cero. Sustituir `ReLU` por `nn.LeakyReLU(negative_slope=0.01)` o `nn.GELU()`.

4. **Uso de Regularización: BatchNorm vs. LayerNorm vs. Dropout:**
   - En arquitecturas MLP tabulares con mini-lotes grandes ($B \ge 64$), utilizar `BatchNorm1d` inmediatamente después de la capa lineal y antes de la activación.
   - Si el tamaño de lote es muy pequeño ($B < 16$), sustituir por `LayerNorm` para evitar la inestabilidad de las medias de lote ruidosas.
   - Emplear **Inverted Dropout** ($p \in [0.1, 0.3]$) exclusivamente en las capas más anchas para mitigar co-adaptaciones complejas, recordando apagar el modo de entrenamiento (`model.eval()`) en la fase de inferencia.
