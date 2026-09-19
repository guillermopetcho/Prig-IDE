# Análisis Exhaustivo de Papers Seminales: Transformers, Mecanismos de Autoatención y Modelos Fundacionales

---

## 1. Ficha Bibliográfica y Contexto Histórico-Científico

### 1.1. Las Publicaciones Fundacionales

* **Paper Seminal de la Arquitectura Transformer:**
  * **Título:** *Attention Is All You Need*
  * **Autores:** Ashish Vaswani, Noam Shazeer, Niki Parmar, Jakob Uszkoreit, Llion Jones, Aidan N. Gomez, Łukasz Kaiser, Illia Polosukhin.
  * **Afiliación:** Google Brain, Google Research, University of Toronto.
  * **Fecha de Publicación:** 12 de junio de 2017 (arXiv:1706.03762); *Advances in Neural Information Processing Systems (NeurIPS 2017)*, Long Beach, CA, EE. UU.
  * **Impacto Histórico:** Considerado unánimemente el trabajo científico más influyente del aprendizaje profundo en el siglo XXI. Eliminó la necesidad de recurrencia temporal y convoluciones espaciales en el modelado de secuencias, instaurando la atención como primitiva de cómputo universal y cimentando la era moderna de los Modelos Fundacionales y Large Language Models (LLMs).

* **Orígenes del Mecanismo de Atención en Redes Neuronales:**
  * **Atención Aditiva en RNNs:** Dzmitry Bahdanau, Kyunghyun Cho, Yoshua Bengio (2014). *Neural Machine Translation by Jointly Learning to Align and Translate*. ICLR 2015. Introdujo el concepto de vector de contexto dinámico ponderado por alineación blanda (*soft-alignment*).
  * **Atención Multiplicativa Global y Local:** Minh-Thang Luong, Hieu Pham, Christopher D. Manning (2015). *Effective Approaches to Attention-based Neural Machine Translation*. EMNLP 2015. Formuló el producto escalar $h_t^T \bar{h}_s$ y demostró la superioridad computacional del producto punto sobre redes feed-forward de alineación.

* **Evolución Estructural y Escalamiento Moderno:**
  * **Layer Normalization:** Jimmy Lei Ba, Jamie Ryan Kiros, Geoffrey E. Hinton (2016). *Layer Normalization*. arXiv:1607.06450. Estabilización de activaciones neuronales invariante al tamaño de lote (*batch size*).
  * **Pre-LN vs. Post-LN:** Ruibin Xiong, Yichuan Yang, Di He, Kai Zheng, Shuxin Zheng, Chen Xing, Huishuai Zhang, Yanyan Lan, Liwei Wang, Tie-Yan Liu (2020). *On Layer Normalization in the Transformer Architecture*. ICML 2020. Demostración teórica del gradiente evanescente en capas inferiores en Post-LN y justificación de Pre-LN para eliminar el requisito de warm-up.
  * **Codificación Posicional Rotatoria (RoPE):** Jianlin Su, Yu Lu, Shengfeng Pan, Ahmed Murtadha, Bo Wen, Yunfeng Liu (2021). *RoFormer: Enhanced Transformer with Rotary Position Embedding*. Neurocomputing 2024. Fusión de propiedades absolutas y relativas mediante rotación ortogonal de subespacios bidimensionales.
  * **Aceleración Hardware e IO-Awareness (FlashAttention):** Tri Dao, Daniel Y. Fu, Stefano Ermon, Atri Rudra, Christopher Ré (2022). *FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness*. NeurIPS 2022. Particionamiento por bloques en memoria SRAM de GPU para evadir el cuello de botella de memoria HBM.
  * **Activaciones Gated y Variantes MLP (SwiGLU):** Noam Shazeer (2020). *GLU Variants Improve Transformer*. arXiv:2002.05202. Sustitución de ReLU/GELU estándar por compuertas bilineales multiplicativas.
  * **Atención Multiconsulta y por Grupos (MQA / GQA):** Noam Shazeer (2019). *Fast Transformer Decoding: One Write-Head is All You Need*; Joshua Ainslie et al. (2023). *GQA: Training Generalized Multi-Query Transformer Models from Multi-Head Checkpoints*. Reducción drástica del ancho de banda del KV-Cache en decodificación.

---

## 2. Génesis Teórica y Ruptura de Paradigma

### 2.1. El Cuello de Botella Secuencial de la Recurrencia ($\mathcal{O}(T)$)
Previo al Transformer (2017), el estándar dominante en procesamiento de lenguaje natural y modelado de secuencias eran las redes neuronales recurrentes (RNN, LSTM, GRU). La formulación intrínseca de una red recurrente:
$$h_t = \phi(W_h h_{t-1} + W_x x_t + b)$$
impone una dependencia estrictamente secuencial: el cómputo del estado oculto en el tiempo $t$ depende de manera obligatoria e insoslayable del vector $h_{t-1}$ del paso temporal previo. 

Esta naturaleza serial acarrea dos limitaciones fundamentales:
1. **Incompatibilidad con Hardware Masivamente Paralelo:** Las GPUs y TPUs modernas basan su aceleración en miles de núcleos de cómputo aritmético ejecutando operaciones de álgebra lineal densa (GEMM) en paralelo. En una RNN, la dimensión temporal $T$ no puede paralelizarse durante el entrenamiento; el tiempo de ejecución escala linealmente como $\mathcal{O}(T)$, forzando a los núcleos de cómputo a permanecer ociosos esperando la sincronización paso a paso.
2. **Degradación de Memoria por Longitud de Camino de Señal (*Maximum Path Length*):** Para que la información de la posición $t_1$ alcance a la posición $t_2$, la señal debe viajar a través de $|t_2 - t_1|$ transformaciones recurrentes consecutivas. En una secuencia de longitud $T$, la distancia máxima de propagación es $\mathcal{O}(T)$. A pesar de compuertas avanzadas como en LSTM o GRU, la acumulación sucesiva de multiplicaciones jacobianas degrada exponencialmente la fidelidad del gradiente y el contenido semántico.

```
Longitud de Camino de Señal (Signal Path Length):
Recurrente (RNN/LSTM):     [x_1] ---> [x_2] ---> [x_3] ---> ... ---> [x_T]     Distancia: O(T)
Convolucional Dilatada:    [x_1]   [x_2]   [x_3]   [x_4]   ...       [x_T]     Distancia: O(log_k T)
                           \_____/ \_____/ \_____/ \_____/
Autoatención (Transformer):Cualquier x_i conecta con cualquier x_j directamente: Distancia: O(1)
```

Las arquitecturas convolucionales para secuencias (como ByteNet o WaveNet) lograron paralelizar el entrenamiento a lo largo de $T$, pero la interacción entre dos tokens separados por distancia $k$ requería apilar múltiples capas convolucionales con dilatación exponencial, dando un camino de señal de orden $\mathcal{O}(\log_k T)$.

### 2.2. La Atención como Primitiva Computacional Única
Vaswani et al. tomaron una decisión conceptual radical: despojar a la arquitectura de toda recurrencia y toda convolución. La atención ya no es un "mecanismo auxiliar de alineación" injertado sobre un codificador-decodificador recurrente, sino la **primitiva de cómputo central y exclusiva** para modelar dependencias sintácticas y semánticas.

En un Transformer, la distancia de interacción entre cualquier par de tokens de la secuencia es estrictamente $\mathcal{O}(1)$: un único paso matricial conecta el primer token con el último mediante producto interno en el espacio de atención.

---

## 3. Formulación y Derivaciones Matemáticas Rigurosas

### 3.1. Scaled Dot-Product Attention (Atención de Producto Escalar Escalado)

Dadas tres matrices construidas a partir de representaciones de secuencias:
* **Consultas ($Q$ - Queries):** $Q \in \mathbb{R}^{n \times d_k}$ (donde $n$ es la longitud de la secuencia objetivo).
* **Claves ($K$ - Keys):** $K \in \mathbb{R}^{m \times d_k}$ (donde $m$ es la longitud de la secuencia fuente).
* **Valores ($V$ - Values):** $V \in \mathbb{R}^{m \times d_v}$ (vectores de contenido).

La función de atención se define analíticamente como:
$$\text{Attention}(Q, K, V) = \text{softmax}\left( \frac{Q K^T}{\sqrt{d_k}} + M \right) V$$
donde $M \in \mathbb{R}^{n \times m}$ representa una matriz opcional de máscara (por ejemplo, causal o de relleno).

```
Flujo Tensorial del Scaled Dot-Product Attention:
  Q (n x d_k)   x   K^T (d_k x m)  --->  Scores S = Q K^T (n x m)
                                                   |
                                            Escalar por 1 / sqrt(d_k)
                                                   |
                                            Sumar Máscara Causal M
                                                   |
                                            Softmax por filas
                                                   |
                                          Matriz de Atención A (n x m)
                                                   |
  A (n x m)     x   V (m x d_v)    --->  Salida O (n x d_v)
```

---

### 3.2. Teorema y Demostración: La Necesidad del Factor de Escala $\frac{1}{\sqrt{d_k}}$

Uno de los aportes matemáticos más sutiles y cruciales de Vaswani et al. es la introducción del divisor $\sqrt{d_k}$. Si bien el producto escalar simple $Q K^T$ es intuitivo, sin este escalamiento el modelo colapsa numéricamente durante el entrenamiento cuando $d_k$ crece.

#### Enunciado Teórico
Sean las componentes de un vector de consulta $q \in \mathbb{R}^{d_k}$ y un vector de clave $k \in \mathbb{R}^{d_k}$ variables aleatorias independientes e idénticamente distribuidas (i.i.d.) con media cero y varianza unitaria:
$$\mathbb{E}[q_i] = 0, \quad \text{Var}(q_i) = 1, \quad \mathbb{E}[k_i] = 0, \quad \text{Var}(k_i) = 1 \quad \forall i \in \{1, \dots, d_k\}$$
Asumimos además mutua independencia entre consultas y claves: $\text{Cov}(q_i, k_j) = 0$.

El producto escalar entre ambos vectores se define como:
$$s = q \cdot k = \sum_{i=1}^{d_k} q_i k_i$$

#### Cálculo de la Esperanza
Por linealidad de la esperanza y la hipótesis de independencia:
$$\mathbb{E}[s] = \sum_{i=1}^{d_k} \mathbb{E}[q_i k_i] = \sum_{i=1}^{d_k} \mathbb{E}[q_i] \mathbb{E}[k_i] = \sum_{i=1}^{d_k} 0 \cdot 0 = 0$$

#### Cálculo de la Varianza
La varianza del producto de dos variables independientes $X$ e $Y$ responde a la identidad:
$$\text{Var}(XY) = \text{Var}(X)\text{Var}(Y) + \text{Var}(X)(\mathbb{E}[Y])^2 + \text{Var}(Y)(\mathbb{E}[X])^2$$
Dado que $\mathbb{E}[q_i] = 0$ y $\mathbb{E}[k_i] = 0$:
$$\text{Var}(q_i k_i) = \text{Var}(q_i)\text{Var}(k_i) + 0 + 0 = 1 \times 1 = 1$$
Como los términos $q_i k_i$ son independientes para cada coordenada $i$:
$$\text{Var}(s) = \sum_{i=1}^{d_k} \text{Var}(q_i k_i) = \sum_{i=1}^{d_k} 1 = d_k$$
La desviación estándar del producto escalar no escalado es:
$$\sigma_s = \sqrt{\text{Var}(s)} = \sqrt{d_k}$$

#### Efecto en la Dinámica del Softmax y Desvanecimiento de Gradientes
Consideremos el vector de logits de atención $z = \frac{s}{\tau}$, donde $\tau$ es un factor de escala y aplicamos la función softmax:
$$\alpha_j = \text{softmax}(z)_j = \frac{e^{z_j}}{\sum_{l=1}^m e^{z_l}}$$
El gradiente local del softmax viene dado por la matriz jacobiana:
$$\frac{\partial \alpha_j}{\partial z_i} = \alpha_j (\delta_{ji} - \alpha_i)$$
* **Caso $\tau = 1$ (sin escalar):** Conforme la dimensión de proyección $d_k$ aumenta (ej. $d_k = 64$ o $128$), $\sigma_s = \sqrt{64} = 8$ o $\sigma_s = \sqrt{128} \approx 11.31$. Valores muestreados aleatoriamente de una distribución normal con varianza $d_k$ arrojarán logits extremos ($z_j \gg z_l$). 
Cuando una componente $z_{\text{max}}$ domina fuertemente, $\alpha_{\text{max}} \to 1$ y $\alpha_{l \neq \text{max}} \to 0$.
En este régimen de saturación:
$$\frac{\partial \alpha_{\text{max}}}{\partial z_{\text{max}}} \approx 1 \times (1 - 1) = 0$$
$$\frac{\partial \alpha_j}{\partial z_i} \approx 0 \times (\delta_{ji} - 0) = 0$$
Los gradientes hacia las consultas y claves se desvanecen prácticamente a cero ($\nabla_Q \mathcal{L} \to 0, \nabla_K \mathcal{L} \to 0$), bloqueando por completo el aprendizaje mediante descenso de gradiente.

* **Caso $\tau = \sqrt{d_k}$ (escalado propuesto por Vaswani):**
Definiendo $z_i = \frac{s_i}{\sqrt{d_k}}$:
$$\text{Var}(z_i) = \text{Var}\left( \frac{s_i}{\sqrt{d_k}} \right) = \frac{1}{d_k} \text{Var}(s_i) = \frac{d_k}{d_k} = 1$$
La varianza de las entradas al softmax se mantiene **rigurosamente unitaria e independiente de la dimensionalidad del modelo**, preservando los logits dentro de la región activa del softmax donde los gradientes son óptimos y estables.

---

### 3.3. Derivación Analítica Completa del Gradiente de la Atención

Sea la pérdida escalar $\mathcal{L}$. Dadas las matrices $Q \in \mathbb{R}^{n \times d_k}$, $K \in \mathbb{R}^{m \times d_k}$, $V \in \mathbb{R}^{m \times d_v}$, definimos los pasos intermedios:
1. $S = \frac{Q K^T}{\sqrt{d_k}} \in \mathbb{R}^{n \times m}$
2. $A = \text{softmax}_{\text{fila}}(S) \in \mathbb{R}^{n \times m}$ tal que $A_{ij} = \frac{e^{S_{ij}}}{\sum_{l=1}^m e^{S_{il}}}$
3. $O = A V \in \mathbb{R}^{n \times d_v}$

Asumimos conocido el gradiente aguas arriba $\frac{\partial \mathcal{L}}{\partial O} \in \mathbb{R}^{n \times d_v}$.

#### Paso 1: Gradiente respecto a los Valores ($V$) y Matriz de Atención ($A$)
Por cálculo multivariable sobre el producto matricial $O = A V$:
$$\frac{\partial \mathcal{L}}{\partial V} = A^T \frac{\partial \mathcal{L}}{\partial O} \quad \in \mathbb{R}^{m \times d_v}$$
$$\frac{\partial \mathcal{L}}{\partial A} = \frac{\partial \mathcal{L}}{\partial O} V^T \quad \in \mathbb{R}^{n \times m}$$

#### Paso 2: Retropropagación a través del Softmax por Fila
Sea $G_A = \frac{\partial \mathcal{L}}{\partial A}$. Para cada fila independiente $i \in \{1, \dots, n\}$:
$$A_{ij} = \text{softmax}(S_i)_j$$
La derivada de la pérdida respecto al elemento del logit $S_{ij}$ es:
$$\frac{\partial \mathcal{L}}{\partial S_{ij}} = \sum_{l=1}^m \frac{\partial \mathcal{L}}{\partial A_{il}} \frac{\partial A_{il}}{\partial S_{ij}} = \sum_{l=1}^m (G_A)_{il} A_{il} (\delta_{lj} - A_{ij}) = (G_A)_{ij} A_{ij} - A_{ij} \sum_{l=1}^m (G_A)_{il} A_{il}$$
En notación matricial vectorizada:
$$D_i = \sum_{l=1}^m (G_A)_{il} A_{il} = (G_A \odot A) \mathbf{1}_{m \times 1}$$
$$\frac{\partial \mathcal{L}}{\partial S} = A \odot \left( G_A - D \mathbf{1}_{1 \times m} \right)$$
donde $\odot$ es el producto de Hadamard elemento a elemento.

#### Paso 3: Gradientes respecto a Consultas ($Q$) y Claves ($K$)
Sabiendo que $S = \frac{1}{\sqrt{d_k}} Q K^T$:
$$\frac{\partial \mathcal{L}}{\partial Q} = \frac{1}{\sqrt{d_k}} \left( \frac{\partial \mathcal{L}}{\partial S} \right) K \quad \in \mathbb{R}^{n \times d_k}$$
$$\frac{\partial \mathcal{L}}{\partial K} = \frac{1}{\sqrt{d_k}} \left( \frac{\partial \mathcal{L}}{\partial S} \right)^T Q \quad \in \mathbb{R}^{m \times d_k}$$

---

### 3.4. Multi-Head Attention (Atención Multicabezal)

En lugar de calcular una única función de atención con dimensión de clave completa $d_{\text{model}}$, Vaswani et al. proyectan linealmente las consultas, claves y valores $h$ veces con diferentes matrices aprendibles de dimensionalidad reducida $d_k = d_v = d_{\text{model}} / h$:
$$\text{head}_i = \text{Attention}(Q W_i^Q, K W_i^K, V W_i^V), \quad i \in \{1, \dots, h\}$$
$$\text{MultiHead}(Q, K, V) = \text{Concat}(\text{head}_1, \dots, \text{head}_h) W^O$$
donde:
* $W_i^Q \in \mathbb{R}^{d_{\text{model}} \times d_k}$
* $W_i^K \in \mathbb{R}^{d_{\text{model}} \times d_k}$
* $W_i^V \in \mathbb{R}^{d_{\text{model}} \times d_v}$
* $W^O \in \mathbb{R}^{(h \cdot d_v) \times d_{\text{model}}} = \mathbb{R}^{d_{\text{model}} \times d_{\text{model}}}$

#### Justificación en Subespacios de Representación
Un único cabezal de atención promedia la información de todos los tokens ponderados, actuando como un centro de gravedad semántico. Los múltiples cabezales permiten al modelo atender simultáneamente a información de diversos subespacios semánticos ortogonales:
* Un cabezal puede especializarse en relaciones sintácticas de corto alcance (verbo - objeto).
* Otro cabezal puede rastrear correferencias pronominales a muy largo alcance (ej. "ella" refiriéndose a un sujeto introducido 200 tokens atrás).
* Otros cabezales capturan dependencias morfológicas, de puntuación o relaciones posicionales estrictas.

---

### 3.5. Inyección de Información Posicional: De Sinusoidal a RoPE

Dado que la función de autoatención es estrictamente equivariante ante permutaciones del conjunto de entrada:
$$\text{Attention}(\Pi X, \Pi X, \Pi X) = \Pi \text{Attention}(X, X, X)$$
si el orden de las palabras se altera, las salidas resultantes simplemente se permutan sin que cambien sus valores vectoriales intrínsecos. Por ende, la información de orden debe ser inyectada explícitamente.

#### 1. Codificación Sinusoidal Absoluta (Vaswani et al. 2017)
Se añade directamente al vector de embedding un vector $PE \in \mathbb{R}^{d_{\text{model}}}$ precomputado mediante funciones armónicas:
$$PE_{(pos, 2i)} = \sin\left( \frac{pos}{10000^{2i / d_{\text{model}}}} \right)$$
$$PE_{(pos, 2i+1)} = \cos\left( \frac{pos}{10000^{2i / d_{\text{model}}}} \right)$$
donde $pos \in [0, T-1]$ es la posición del token y $i \in [0, d_{\text{model}}/2 - 1]$ indexa la frecuencia angular:
$$\omega_i = 10000^{-2i / d_{\text{model}}}$$
* **Propiedad de Desplazamiento Lineal:** Mediante las identidades trigonométricas de suma de ángulos:
  $$\sin(\omega (pos + k)) = \sin(\omega pos)\cos(\omega k) + \cos(\omega pos)\sin(\omega k)$$
  $$\cos(\omega (pos + k)) = \cos(\omega pos)\cos(\omega k) - \sin(\omega pos)\sin(\omega k)$$
  Existe una transformación lineal fija $M_k \in \mathbb{R}^{2 \times 2}$ tal que:
  $$\begin{pmatrix} PE_{(pos+k, 2i)} \\ PE_{(pos+k, 2i+1)} \end{pmatrix} = \begin{pmatrix} \cos(k \omega_i) & \sin(k \omega_i) \\ -\sin(k \omega_i) & \cos(k \omega_i) \end{pmatrix} \begin{pmatrix} PE_{(pos, 2i)} \\ PE_{(pos, 2i+1)} \end{pmatrix}$$
  Esto permite teóricamente que el modelo aprenda a atender por desplazamientos relativos constantes $k$. Sin embargo, la suma directa con los embeddings corrompe parcialmente el espacio semántico.

#### 2. Rotary Position Embedding (RoPE - Su et al. 2021)
RoPE resuelve el problema de inyectar posición relativa sin sumar ruido al embedding, aplicando una rotación ortogonal directa sobre los vectores de consulta y clave en el plano complejo.

* **Condición Deseada:** Buscamos una función de mapeo $\tilde{q}_m = f_q(q, m)$ y $\tilde{k}_n = f_k(k, n)$ tal que su producto escalar dependa únicamente de la distancia relativa $(m - n)$:
  $$\langle f_q(q, m), f_k(k, n) \rangle = g(q, k, m - n)$$

* **Solución Geométrica:** Dividiendo el vector de consulta $q \in \mathbb{R}^{d}$ en pares bidimensionales de coordenadas $(q_{2i}, q_{2i+1})$, interpretados como números complejos $z_{q, i} = q_{2i} + j q_{2i+1} \in \mathbb{C}$, la rotación por un ángulo proporcional a la posición $m$ y frecuencia $\theta_i = 10000^{-2i/d}$ es:
  $$\tilde{z}_{q, i} = z_{q, i} e^{j m \theta_i}$$
  $$\tilde{z}_{k, i} = z_{k, i} e^{j n \theta_i}$$

El producto escalar real entre ambos subvectores rotados en $\mathbb{R}^2$ equivale a la parte real del producto complejo conjugado:
$$\langle \tilde{q}^{(i)}_m, \tilde{k}^{(i)}_n \rangle = \text{Re}(\tilde{z}_{q, i} \tilde{z}_{k, i}^*) = \text{Re}\left( (z_{q, i} e^{j m \theta_i}) (z_{k, i}^* e^{-j n \theta_i}) \right) = \text{Re}\left( z_{q, i} z_{k, i}^* e^{j (m - n) \theta_i} \right)$$
El resultado final depende **estrictamente de $(m - n)$**, preservando la traslación temporal invariante.

En notación matricial sobre $\mathbb{R}^d$, la transformación es una matriz ortogonal diagonal por bloques:
$$R_{\Theta, m} = \text{diag}\left( R_{\theta_0, m}, R_{\theta_1, m}, \dots, R_{\theta_{d/2 - 1}, m} \right)$$
$$R_{\theta_i, m} = \begin{pmatrix} \cos(m \theta_i) & -\sin(m \theta_i) \\ \sin(m \theta_i) & \cos(m \theta_i) \end{pmatrix}$$
Dado que $R_{\Theta, m}^T R_{\Theta, n} = R_{\Theta, n - m}$:
$$\langle R_{\Theta, m} q, R_{\Theta, n} k \rangle = q^T R_{\Theta, m}^T R_{\Theta, n} k = q^T R_{\Theta, n - m} k$$
La rotación puede calcularse de manera sumamente eficiente sin construir matrices explícitas:
$$R_{\Theta, m} x = x \odot \cos(m \Theta) + \tilde{x} \odot \sin(m \Theta)$$
donde $\tilde{x} = (-x_1, x_0, -x_3, x_2, \dots)$.

---

### 3.6. Estabilidad del Gradiente: Post-LN vs. Pre-LN y RMSNorm

En el paper original de Vaswani (2017), la normalización por capas (*LayerNorm*) se disponía en esquema **Post-LN**:
$$x_{l+1} = \text{LN}\left( x_l + \text{SubLayer}(x_l) \right)$$

```
Esquemas de Conexión y Flujo de Gradiente:

Post-LN (Vaswani 2017):
x_l ---> [ SubLayer ] ---> (+) ---> [ LayerNorm ] ---> x_{l+1}
  |________________________^
  Gradiente forzado a través de d(LN)/dx en cada capa: Decaimiento exponencial.

Pre-LN (Xiong et al. 2020 / Modern LLMs):
x_l ---> [ LayerNorm ] ---> [ SubLayer ] ---> (+) ---> x_{l+1}
  |                                            ^
  |_________________ (Highway Residual Puro) ___|
  Gradiente fluye directamente sin obstáculo: d(x_{l+1})/d(x_l) = I + ...
```

#### El Teorema de Xiong et al. (2020)
Ruibin Xiong et al. demostraron formalmente que en Post-LN:
* Para una red de $L$ capas, el gradiente de la pérdida respecto a los parámetros de las capas iniciales decae a una tasa de $\mathcal{O}\left(\frac{1}{L}\right)$ o exponencialmente, mientras que en las capas finales es de orden $\mathcal{O}(1)$.
* Esto obliga a utilizar un régimen de *learning rate warmup* estricto y prolongado (cientos o miles de pasos con tasa de aprendizaje microscópica); sin warm-up, el entrenamiento en Post-LN diverge de inmediato en las primeras iteraciones.

En contraposición, en el esquema **Pre-LN**:
$$x_{l+1} = x_l + \text{SubLayer}(\text{LN}(x_l))$$
La conexión residual pura $x_{l+1} = x_l + \dots$ actúa como una verdadera "superautopista" (*gradient highway*). Al expandir la recursión:
$$x_L = x_0 + \sum_{l=0}^{L-1} \text{SubLayer}(\text{LN}(x_l))$$
La derivada del estado final respecto a una capa temprana $l$ es:
$$\frac{\partial x_L}{\partial x_l} = I + \sum_{j=l}^{L-1} \frac{\partial \text{SubLayer}(\text{LN}(x_j))}{\partial x_l}$$
El término de identidad $I$ garantiza que los gradientes viajen sin atenuación hasta la primera capa, permitiendo entrenar sin *warm-up* y alcanzando convergencias extraordinariamente estables en modelos profundos.

#### RMSNorm (Root Mean Square Normalization - Zhang & Sennrich 2019)
LayerNorm estándar computa:
$$\text{LN}(x) = \frac{x - \mu}{\sqrt{\sigma^2 + \epsilon}} \odot \gamma + \beta$$
donde $\mu = \frac{1}{d} \sum_{i=1}^d x_i$ y $\sigma^2 = \frac{1}{d} \sum_{i=1}^d (x_i - \mu)^2$.

Zhang & Sennrich demostraron que la propiedad que estabiliza el gradiente no es el desplazamiento de la media $\mu$, sino el reescalamiento por la magnitud cuadrática. Formulando **RMSNorm**:
$$\text{RMSNorm}(x) = \frac{x}{\text{RMS}(x)} \odot \gamma, \quad \text{donde } \text{RMS}(x) = \sqrt{\frac{1}{d} \sum_{i=1}^d x_i^2 + \epsilon}$$
RMSNorm elimina la necesidad de centrar por la media y prescinde del vector de sesgo $\beta$, ahorrando un $7\%$ a $10\%$ del tiempo de cómputo de la capa de normalización sin merma alguna en capacidad de generalización (adoptado en LLaMA, Mistral, Gemma).

---

## 4. Arquitectura de Sistemas, Complejidad y Algoritmos de Aceleración

### 4.1. Análisis Comparativo de Complejidad Asintótica

| Operación / Capa | Complejidad por Capa (FLOPS) | Complejidad Secuencial Mínima | Longitud Máxima de Camino | Memoria de Activación |
| :--- | :--- | :--- | :--- | :--- |
| **Self-Attention** | $\mathcal{O}(T^2 \cdot d)$ | $\mathcal{O}(1)$ | $\mathcal{O}(1)$ | $\mathcal{O}(B \cdot H \cdot T^2)$ |
| **Recurrente (LSTM)** | $\mathcal{O}(T \cdot d^2)$ | $\mathcal{O}(T)$ | $\mathcal{O}(T)$ | $\mathcal{O}(B \cdot T \cdot d)$ |
| **Convolución Estándar** | $\mathcal{O}(T \cdot k \cdot d^2)$ | $\mathcal{O}(1)$ | $\mathcal{O}(\log_k T)$ | $\mathcal{O}(B \cdot T \cdot d)$ |
| **Feed-Forward (MLP)** | $\mathcal{O}(T \cdot d_{\text{model}} \cdot d_{\text{ff}})$ | $\mathcal{O}(1)$ | $\mathcal{O}(1)$ | $\mathcal{O}(B \cdot T \cdot d_{\text{ff}})$ |

*Nota Crítica:* Para secuencias donde $T < d$, la autoatención es computacionalmente más rápida que una capa recurrente ($\mathcal{O}(T^2 d) < \mathcal{O}(T d^2)$). Sin embargo, cuando la longitud de contexto se expande a $T = 32\text{k}, 128\text{k}$ o $1\text{M}$ tokens, el término cuadrático $T^2$ domina y convierte la atención en el cuello de botella fundamental en cómputo y memoria.

---

### 4.2. Inferencia Autoregresiva y el Mecanismo de KV-Cache

En generación de texto token a token, la propiedad autorregresiva dicta que para predecir el token en el tiempo $t+1$:
$$x_{t+1} \sim P(x_{t+1} \mid x_1, x_2, \dots, x_t)$$
* **Sin KV-Cache (Naive):** En cada paso $t$, se pasa toda la secuencia previa $x_{1:t}$ por la red. Se recalculan innecesariamente las proyecciones $K_{1:t}$ y $V_{1:t}$ de todos los tokens pasados. El costo total para generar $N$ tokens nuevos sobre un prompt de longitud $P$ es:
  $$\text{Costo}_{\text{Naive}} = \sum_{t=P}^{P+N-1} \mathcal{O}(t \cdot d) \approx \mathcal{O}(N \cdot P \cdot d + \frac{1}{2} N^2 d)$$
* **Con KV-Cache:** Las claves y valores de las posiciones $1$ a $t-1$ ya fueron computadas y son invariantes en el tiempo (debido a la máscara causal). Por lo tanto, se almacenan en memoria DRAM/HBM de la GPU:
  * En el paso $t$, únicamente proyectamos el token nuevo: $q_t = x_t W^Q$, $k_t = x_t W^K$, $v_t = x_t W^V$.
  * Concatenamos $k_t$ y $v_t$ al buffer: $K_{\text{cache}} \leftarrow [K_{\text{cache}}; k_t]$, $V_{\text{cache}} \leftarrow [V_{\text{cache}}; v_t]$.
  * Calculamos el producto escalar únicamente de $q_t$ (vector de $1 \times d_k$) contra todo $K_{\text{cache}}^T$ (matriz de $d_k \times t$).
  * El cómputo en el paso $t$ se reduce drásticamente de matriz $\times$ matriz a vector $\times$ matriz (GEMV).

```
Mecanismo de KV-Cache en Paso Temporal t:
Tokens pasados:   [x_1, x_2, ..., x_{t-1}] ---> Ya en KV-Cache: K_{1:t-1}, V_{1:t-1}
Token nuevo:      [x_t] ----------------------> Computa solo: q_t (1 x d), k_t (1 x d), v_t (1 x d)
                                                Append k_t, v_t al KV-Cache
Atención en t:    Scores = q_t * [K_{cache}]^T (1 x t) ---> Softmax ---> Pondera [V_{cache}] (1 x d)
```

#### Huella de Memoria del KV-Cache
La memoria requerida para retener el KV-Cache en un modelo autoregresivo viene dada exactamente por:
$$\text{Memoria}_{\text{KV-Cache}} = 2 \times 2 \times n_{\text{layers}} \times n_{\text{kv\_heads}} \times d_{\text{head}} \times T_{\text{ctx}} \times B \quad \text{bytes (en precisión FP16/BF16)}$$
donde:
* El primer factor $2$ corresponde a almacenar dos matrices: $K$ y $V$.
* El segundo factor $2$ corresponde al tamaño en bytes de `fp16` o `bf16` (2 bytes por parámetro).
* $n_{\text{layers}}$: número de bloques de atención.
* $n_{\text{kv\_heads}}$: número de cabezales de claves y valores ($= h$ en MHA, $= 1$ en MQA, $< h$ en GQA).
* $d_{\text{head}}$: dimensión por cabezal ($d_{\text{model}} / h$).
* $T_{\text{ctx}}$: longitud total del contexto actual.
* $B$: tamaño de lote (*batch size*).

*Ejemplo Real:* En LLaMA-2-70B ($L=80$, $h=64$, $d_{\text{head}}=128$, con MHA), para un lote de $B=1$ y contexto de $T=4096$:
$$\text{Memoria} = 4 \times 80 \times 64 \times 128 \times 4096 \times 1 \approx 10.73 \times 10^9 \text{ bytes} \approx 10.74 \text{ GB}$$
¡Solo el KV-Cache consume más de 10 GB de VRAM antes de contar los pesos del modelo ni las activaciones! Esta es la razón por la cual arquitecturas como LLaMA-3 y Mistral adoptaron unánimemente **Grouped-Query Attention (GQA)**, reduciendo $n_{\text{kv\_heads}}$ a 8 y contrayendo la huella a una octava parte (1.34 GB).

---

### 4.3. FlashAttention: La Revolución IO-Aware (Dao et al. 2022)

En las arquitecturas de GPU modernas (NVIDIA A100, H100), la velocidad de procesamiento de los Tensor Cores (centenares de TFLOPS) supera en órdenes de magnitud el ancho de banda de transferencia de datos con la memoria global de alto ancho de banda (HBM).

```
Jerarquía de Memoria en GPU:
+-------------------------------------------------------------+
| GPU Chip                                                    |
|  +-------------------------------------------------------+  |
|  | SRAM On-Chip (Ultrarrápida: ~19 TB/s, Capacidad: ~20 MB) |  |
|  |   [ Tensor Cores / Cómputo GEMM ]                     |  |
|  +-------------------------------------------------------+  |
|                             ^                               |
|                             | Cuello de botella IO          |
|                             v                               |
+-------------------------------------------------------------+
| Memoria Global HBM (Relativamente Lenta: ~2 TB/s, ~80 GB)   |
|   [ Q, K, V, Matriz de Atención Gigante A = N x N ]         |
+-------------------------------------------------------------+
```

* **El Problema de la Atención Estándar:**
  1. Lee $Q, K$ de HBM a SRAM $\to$ computa $S = Q K^T$ $\to$ escribe $S \in \mathbb{R}^{N \times N}$ a HBM. (Lectura/Escritura: $\mathcal{O}(N^2)$).
  2. Lee $S$ de HBM a SRAM $\to$ computa $P = \text{softmax}(S)$ $\to$ escribe $P \in \mathbb{R}^{N \times N}$ a HBM. (Lectura/Escritura: $\mathcal{O}(N^2)$).
  3. Lee $P, V$ de HBM a SRAM $\to$ computa $O = P V$ $\to$ escribe $O \in \mathbb{R}^{N \times d}$ a HBM.
  La complejidad de acceso a memoria es $\mathcal{O}(N^2)$. Para secuencias largas, la GPU pasa el $80\%$ del tiempo esperando la transferencia de datos por el bus de HBM (*memory-bound*), desaprovechando los Tensor Cores.

* **La Solución de FlashAttention:**
  Tri Dao et al. aplicaron dos técnicas magistrales:
  1. **Tiling por Bloques:** Dividir $Q, K, V$ en bloques pequeños de tamaño $B_r \times d$ y $B_c \times d$ que quepan íntegramente en la memoria SRAM on-chip ultra rápida (~100 KB a 20 MB).
  2. **Softmax Incremental / Online Softmax:** Softmax requiere conocer el máximo global de la fila para evitar desbordamiento numérico. FlashAttention utiliza el truco de actualización de suma y escala de Milakov & Gimelshein (2018):
     Dada una partición de la fila en bloques $S^{(1)}$ y $S^{(2)}$:
     $$m^{(1)} = \max(S^{(1)}), \quad \ell^{(1)} = \sum e^{S^{(1)}_j - m^{(1)}}$$
     Al procesar el nuevo bloque con máximo $m^{(2)}$:
     $$m^{\text{new}} = \max(m^{(1)}, m^{(2)})$$
     $$\ell^{\text{new}} = e^{m^{(1)} - m^{\text{new}}} \ell^{(1)} + \sum e^{S^{(2)}_j - m^{\text{new}}}$$
     Permite actualizar la salida acumulada $O$ en un solo paso hacia adelante en SRAM sin jamás materializar ni escribir la colosal matriz intermedia $N \times N$ a HBM.
  * **Resultado:** Reduce el tráfico de HBM de $\mathcal{O}(N^2)$ a $\mathcal{O}(N \cdot d)$ accesos, acelerando el entrenamiento de 2x a 4x y permitiendo escalar ventanas de contexto a decenas de miles de tokens con memoria lineal.

---

## 5. Tabla Comparativa de Variantes Arquitectónicas

| Paradigma | Modelo Canónico | Patrón de Atención | Ventajas Principales | Debilidades / Limitaciones | Caso de Uso Óptimo |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Encoder-Only** | BERT, RoBERTa, DeBERTa | **Bidireccional Total:** cada token atiende a todos los tokens pasados y futuros ($M=0$). | Captura contexto contextual profundo a izquierda y derecha simultáneamente. | Ineficiente para generación abierta de texto autorregresivo. | Clasificación de texto, Named Entity Recognition (NER), embeddings semánticos, búsqueda vectorial. |
| **Decoder-Only** | GPT-4, LLaMA-3, Mistral, Claude | **Causal / Autorregresivo:** máscara triangular superior ($M_{ij} = -\infty$ para $j > i$). | Simplicidad arquitectónica, unificación de tareas vía modelado de lenguaje autorregresivo y compatibilidad con KV-Cache. | No puede condicionar en tokens futuros durante la codificación del prompt. | Generación de lenguaje natural, razonamiento lógico, codificación de software, asistentes conversacionales. |
| **Encoder-Decoder** | T5, BART, Vaswani original (2017) | **Híbrido:** Codificador bidireccional + Decodificador causal + Cross-Attention ($Q_{\text{dec}}, K_{\text{enc}}, V_{\text{enc}}$). | Separación estricta entre representación de entrada y generación de salida condicional. | Mayor complejidad de hiperparámetros, latencia añadida en inferencia cruzada. | Traducción automática, resumen abstracto de texto largo, transformación multimodal (ej. Whisper, Gemini Vision). |

---

## 6. Implementación de Referencia en Python/NumPy Puro (Zero-Black-Box)

La siguiente implementación modela fielmente y desde primeros principios:
1. `ScaledDotProductAttention_Puro`: con factor de escala $\frac{1}{\sqrt{d_k}}$, máscara causal opcional y estabilización numérica mediante centrado por el máximo antes de softmax.
2. `RotaryEmbedding_Puro`: cálculo analítico de RoPE bidimensional por pares de coordenadas.
3. `MultiHeadAttention_Puro`: proyecciones matriciales $W^Q, W^K, W^V$ y $W^O$, transposición de cabezales `(B, T, H, D)` y soporte completo de **KV-Cache incremental** para generación autorregresiva token a token.
4. `RMSNorm_Puro` y `SwiGLU_Puro`: capas de normalización y feed-forward modernas de estándar LLaMA.
5. Verificación de equivalencia numérica estricta entre decodificación completa vs. decodificación paso a paso con KV-Cache.

```python
"""
Implementación de Referencia: Transformer Decoder con RoPE, RMSNorm, SwiGLU y KV-Cache
Código riguroso en NumPy puro sin librerías externas de Deep Learning.
"""

import numpy as np


class RMSNorm_Puro:
    """Normalización Root Mean Square (Zhang & Sennrich 2019) sin centrado de media."""
    def __init__(self, d_model: int, eps: float = 1e-6):
        self.d_model = d_model
        self.eps = eps
        # Parámetro de ganancia aprendible (gamma)
        self.gamma = np.ones(d_model, dtype=np.float64)

    def forward(self, x: np.ndarray) -> np.ndarray:
        # x: (Batch, SeqLen, d_model)
        # rms = sqrt(mean(x^2) + eps)
        rms = np.sqrt(np.mean(x ** 2, axis=-1, keepdims=True) + self.eps)
        return (x / rms) * self.gamma


class RotaryEmbedding_Puro:
    """Codificación Posicional Rotatoria (RoPE - Su et al. 2021)."""
    def __init__(self, d_head: int, base: float = 10000.0):
        assert d_head % 2 == 0, "d_head debe ser par para agrupar coordenadas en 2D."
        self.d_head = d_head
        # Frecuencias angulares theta_i = 1 / (base^(2i / d)) para i in [0, d/2 - 1]
        i = np.arange(0, d_head, 2, dtype=np.float64)
        self.theta = 1.0 / (base ** (i / d_head))

    def aplicar_rope(self, x: np.ndarray, offset_pos: int = 0) -> np.ndarray:
        # x: tensor de forma (Batch, Heads, SeqLen, d_head)
        B, H, T, D = x.shape
        posiciones = np.arange(offset_pos, offset_pos + T, dtype=np.float64)
        # ángulos: (SeqLen, D / 2)
        angulos = np.outer(posiciones, self.theta)
        
        # Duplicar cos y sin para emparejar con las coordenadas pares e impares
        cos_m = np.cos(angulos)  # (T, D/2)
        sin_m = np.sin(angulos)  # (T, D/2)
        
        # Intercalar para dar forma (1, 1, T, D)
        cos_tensor = np.repeat(cos_m, 2, axis=-1).reshape(1, 1, T, D)
        sin_tensor = np.repeat(sin_m, 2, axis=-1).reshape(1, 1, T, D)
        
        # Rotación bidimensional por bloques:
        # [-x1, x0, -x3, x2, ...]
        x_rot = np.empty_like(x)
        x_rot[..., 0::2] = -x[..., 1::2]
        x_rot[..., 1::2] = x[..., 0::2]
        
        return (x * cos_tensor) + (x_rot * sin_tensor)


def scaled_dot_product_attention(
    q: np.ndarray,
    k: np.ndarray,
    v: np.ndarray,
    mask: np.ndarray = None
) -> tuple[np.ndarray, np.ndarray]:
    """
    Scaled Dot-Product Attention: softmax(Q K^T / sqrt(d_k) + M) V
    q: (B, H, T_q, d_k)
    k: (B, H, T_k, d_k)
    v: (B, H, T_k, d_v)
    mask: opcional (T_q, T_k) o broadcastable
    """
    d_k = q.shape[-1]
    # Puntuaciones brutas: (B, H, T_q, T_k)
    scores = np.matmul(q, np.swapaxes(k, -1, -2)) / np.sqrt(d_k)
    
    if mask is not None:
        scores = scores + mask
        
    # Softmax numéricamente estable por fila: z - max(z)
    max_scores = np.max(scores, axis=-1, keepdims=True)
    exp_scores = np.exp(scores - max_scores)
    attention_weights = exp_scores / (np.sum(exp_scores, axis=-1, keepdims=True) + 1e-12)
    
    # Salida: (B, H, T_q, d_v)
    output = np.matmul(attention_weights, v)
    return output, attention_weights


class MultiHeadAttention_Puro:
    """Atención Multicabezal con soporte de RoPE y KV-Cache."""
    def __init__(self, d_model: int, n_heads: int, seed: int = 42):
        assert d_model % n_heads == 0
        self.d_model = d_model
        self.n_heads = n_heads
        self.d_head = d_model // n_heads
        
        rng = np.random.default_rng(seed)
        scale = 1.0 / np.sqrt(d_model)
        
        # Pesos de proyección aprendibles
        self.W_q = rng.normal(0, scale, (d_model, d_model))
        self.W_k = rng.normal(0, scale, (d_model, d_model))
        self.W_v = rng.normal(0, scale, (d_model, d_model))
        self.W_o = rng.normal(0, scale, (d_model, d_model))
        
        self.rope = RotaryEmbedding_Puro(self.d_head)
        
        # Buffer de KV-Cache
        self.cache_k = None  # (B, H, T_cached, d_head)
        self.cache_v = None

    def reset_cache(self):
        self.cache_k = None
        self.cache_v = None

    def forward(
        self,
        x: np.ndarray,
        use_causal_mask: bool = True,
        use_cache: bool = False
    ) -> np.ndarray:
        B, T, D = x.shape
        
        # Proyecciones lineales
        q = np.matmul(x, self.W_q)  # (B, T, D)
        k = np.matmul(x, self.W_k)
        v = np.matmul(x, self.W_v)
        
        # Reorganizar en cabezales: (B, H, T, d_head)
        q = q.reshape(B, T, self.n_heads, self.d_head).transpose(0, 2, 1, 3)
        k = k.reshape(B, T, self.n_heads, self.d_head).transpose(0, 2, 1, 3)
        v = v.reshape(B, T, self.n_heads, self.d_head).transpose(0, 2, 1, 3)
        
        # Determinar offset posicional en caso de inferencia con caché
        offset_pos = 0 if self.cache_k is None or not use_cache else self.cache_k.shape[2]
        
        # Aplicar RoPE a q y k
        q = self.rope.aplicar_rope(q, offset_pos=offset_pos)
        k = self.rope.aplicar_rope(k, offset_pos=offset_pos)
        
        # Actualización de KV-Cache
        if use_cache:
            if self.cache_k is None:
                self.cache_k = k
                self.cache_v = v
            else:
                self.cache_k = np.concatenate([self.cache_k, k], axis=2)
                self.cache_v = np.concatenate([self.cache_v, v], axis=2)
            k_atn = self.cache_k
            v_atn = self.cache_v
        else:
            k_atn = k
            v_atn = v
            
        T_k = k_atn.shape[2]
        
        # Construir máscara causal autorregresiva si aplica
        mask = None
        if use_causal_mask:
            # Si estamos generando token a token con caché (T=1), el token nuevo
            # atiende a todas las posiciones pasadas existentes en el caché: no requiere bloqueo.
            if T > 1:
                # Matriz triangular superior con -inf
                mask = np.full((T, T_k), -np.inf)
                # Índices correspondientes a offset_pos
                for row_idx in range(T):
                    max_allowed_col = offset_pos + row_idx
                    mask[row_idx, :max_allowed_col + 1] = 0.0
                mask = mask.reshape(1, 1, T, T_k)

        # Scaled Dot-Product Attention
        out_heads, _ = scaled_dot_product_attention(q, k_atn, v_atn, mask=mask)
        
        # Re-ensamblar cabezales: (B, T, H, d_head) -> (B, T, D)
        out_concat = out_heads.transpose(0, 2, 1, 3).reshape(B, T, D)
        
        # Proyección final W^O
        return np.matmul(out_concat, self.W_o)


class SwiGLU_Puro:
    """Feed-Forward Gated SwiGLU (Shazeer 2020) adoptado en LLaMA."""
    def __init__(self, d_model: int, d_ff: int, seed: int = 42):
        rng = np.random.default_rng(seed)
        scale = 1.0 / np.sqrt(d_model)
        self.W_gate = rng.normal(0, scale, (d_model, d_ff))
        self.W_up = rng.normal(0, scale, (d_model, d_ff))
        self.W_down = rng.normal(0, scale, (d_ff, d_model))

    @staticmethod
    def _silu(z: np.ndarray) -> np.ndarray:
        # SiLU / Swish: z * sigmoid(z)
        return z / (1.0 + np.exp(-np.clip(z, -30.0, 30.0)))

    def forward(self, x: np.ndarray) -> np.ndarray:
        # x: (B, T, d_model)
        gate = self._silu(np.matmul(x, self.W_gate))
        up = np.matmul(x, self.W_up)
        # Multiplicación Hadamard element-wise
        gated = gate * up
        return np.matmul(gated, self.W_down)


class TransformerBlock_Puro:
    """Bloque Decoder de Transformer con arquitectura Pre-LN moderna."""
    def __init__(self, d_model: int, n_heads: int, d_ff: int, seed: int = 42):
        self.norm1 = RMSNorm_Puro(d_model)
        self.mha = MultiHeadAttention_Puro(d_model, n_heads, seed=seed)
        self.norm2 = RMSNorm_Puro(d_model)
        self.ffn = SwiGLU_Puro(d_model, d_ff, seed=seed + 1)

    def forward(self, x: np.ndarray, use_cache: bool = False) -> np.ndarray:
        # Pre-LN para la atención + Conexión residual
        x = x + self.mha.forward(self.norm1.forward(x), use_causal_mask=True, use_cache=use_cache)
        # Pre-LN para el FFN SwiGLU + Conexión residual
        x = x + self.ffn.forward(self.norm2.forward(x))
        return x


if __name__ == "__main__":
    print("=== TEST 1: DEMOSTRACIÓN DE ESTABILIZACIÓN SOFTMAX (1 / sqrt(d_k)) ===")
    d_k_list = [16, 64, 256, 1024]
    for d in d_k_list:
        q = np.random.randn(1000, d)
        k = np.random.randn(1000, d)
        # Producto punto elemento a elemento
        dot_raw = np.sum(q * k, axis=-1)
        dot_scaled = dot_raw / np.sqrt(d)
        print(f"d_k = {d:4d} | Varianza sin escalar: {np.var(dot_raw):8.2f} (Teórica: {d}) | Varianza escalada: {np.var(dot_scaled):6.2f} (Teórica: 1.00)")

    print("\n=== TEST 2: DEMOSTRACIÓN DE ROTARY EMBEDDING (RoPE) ===")
    rope = RotaryEmbedding_Puro(d_head=64)
    # Crear dos vectores aleatorios idénticos en posiciones separadas
    q_vec = np.random.randn(1, 1, 1, 64)
    k_vec = np.random.randn(1, 1, 1, 64)
    
    # Evaluar producto punto a distancia relativa Delta = 5: (pos_q=10, pos_k=5) vs (pos_q=25, pos_k=20)
    q_rot_10 = rope.aplicar_rope(q_vec, offset_pos=10)
    k_rot_5  = rope.aplicar_rope(k_vec, offset_pos=5)
    dot_dist_5_a = np.sum(q_rot_10 * k_rot_5)
    
    q_rot_25 = rope.aplicar_rope(q_vec, offset_pos=25)
    k_rot_20 = rope.aplicar_rope(k_vec, offset_pos=20)
    dot_dist_5_b = np.sum(q_rot_25 * k_rot_20)
    
    print(f"Producto escalar en pos (10, 5)   [Delta=5]: {dot_dist_5_a:.6f}")
    print(f"Producto escalar en pos (25, 20)  [Delta=5]: {dot_dist_5_b:.6f}")
    assert np.isclose(dot_dist_5_a, dot_dist_5_b), "Fallo en propiedad de invariancia traslacional relativa de RoPE!"
    print("-> ¡Invariancia traslacional exacta confirmada en RoPE!")

    print("\n=== TEST 3: EQUIVALENCIA RIGUROSA DE KV-CACHE EN INFERENCIA ===")
    d_model, n_heads, d_ff = 64, 4, 128
    block = TransformerBlock_Puro(d_model=d_model, n_heads=n_heads, d_ff=d_ff, seed=123)
    
    # Secuencia completa de longitud T = 5
    tokens_input = np.random.randn(1, 5, d_model)
    
    # 1. Pase completo en paralelo (Modo entrenamiento / prefill)
    block.mha.reset_cache()
    salida_paralela = block.forward(tokens_input, use_cache=False)
    
    # 2. Pase secuencial token a token utilizando KV-Cache (Modo generación autorregresiva)
    block.mha.reset_cache()
    salidas_cache = []
    for t in range(5):
        token_t = tokens_input[:, t:t+1, :]  # Forma (1, 1, d_model)
        out_t = block.forward(token_t, use_cache=True)
        salidas_cache.append(out_t)
        
    salida_secuencial = np.concatenate(salidas_cache, axis=1)  # (1, 5, d_model)
    
    diferencia_maxima = np.max(np.abs(salida_paralela - salida_secuencial))
    print(f"Diferencia absoluta máxima entre Prefill y KV-Cache: {diferencia_maxima:.2e}")
    assert diferencia_maxima < 1e-10, "Discrepancia numérica entre pase paralelo y secuencial con KV-Cache!"
    print("-> ¡Equivalencia matemática perfecta (error < 1e-10) verificada con éxito!")
```

---

## 7. Directrices de Razonamiento para la IA de Prig IDE

Cuando un modelo de lenguaje en Prig IDE asesore a desarrolladores, audite bases de código de aprendizaje profundo o diseñe modelos fundacionales basados en Transformers, debe apegarse a las siguientes directrices y reglas operativas inviolables:

1. **Regla Inquebrantable de Normalización Pre-LN frente a Post-LN:**
   - Si el usuario plantea implementar un Transformer desde cero con más de 6 capas, **exigir inequívocamente la arquitectura Pre-LN** ($x \leftarrow x + \text{SubLayer}(\text{Norm}(x))$) o RMSNorm.
   - Rechazar arquitecturas Post-LN estándar sin advertir explícitamente que requerirán un calendario de warm-up agresivo y sufrirán de inestabilidad de gradiente en capas profundas conforme a las pruebas de Xiong et al. (2020).

2. **Cálculo Exacto de Memoria para Dimensionamiento de KV-Cache:**
   - Al estimar la capacidad de despliegue en GPUs de inferencia para LLMs, calcular obligatoriamente el KV-Cache con la fórmula analítica:
     $$\text{Memoria}_{\text{KV}} = 4 \times n_{\text{layers}} \times n_{\text{kv\_heads}} \times d_{\text{head}} \times \text{ContextLen} \times \text{BatchSize} \quad (\text{en bytes para FP16})$$
   - Si la huella de KV-Cache supera el $20\%$ de la VRAM disponible, recomendar inmediatamente migrar de MHA a **Grouped-Query Attention (GQA)** con ratio $1:4$ u $1:8$, o adoptar cuantización del KV-Cache a FP8/INT4.

3. **Diagnóstico de Saturación y Colapso de Atención (*Attention Entropy Breakdown*):**
   - Si el usuario reporta que las ponderaciones de atención se distribuyen uniformemente (entropía máxima: el modelo no atiende a nada específico) o que un único token absorbe el $99.9\%$ de la probabilidad en todas las capas (*attention sink*):
     1. Verificar que los scores de atención están divididos estrictamente por $\sqrt{d_k}$. La omisión de este factor es el bug de implementación más común en arquitecturas personalizadas.
     2. En secuencias ultra largas ($>32\text{k}$ tokens), advertir sobre el fenómeno de los primeros tokens absorbiendo masa de atención espuria (Xiao et al., *Efficient Streaming Language Models with Attention Sinks*); la solución recomendada es retener siempre los primeros 4 tokens en el KV-Cache de ventana deslizante.

4. **Escalamiento de Contexto y Frecuencia Base de RoPE ($\theta_{\text{base}}$):**
   - Cuando se amplíe la ventana de contexto de un modelo preentrenado con RoPE (por ejemplo de $4\text{k}$ a $32\text{k}$ o $128\text{k}$ tokens), **desaconsejar la extrapolación lineal ingenua**.
   - Indicar el uso de *RoPE Frequency Base Scaling* (aumentar $\theta_{\text{base}}$ de $10000$ a $500000$ o $1000000$, como en LLaMA-3) o técnicas de interpolación de posición como *YaRN* o *NTK-aware Scaled RoPE*. Justificación: frecuencias altas codifican orden local y no deben estirarse indiscriminadamente; solo las frecuencias bajas (longitudes de onda largas) deben comprimirse.

5. **Aceleración Hardware Obligatoria: Integración de FlashAttention-2 / SDPA:**
   - Para entornos PyTorch $\ge 2.0$, prohibir explícitamente el uso de `torch.bmm(q, k.transpose())` seguido de `torch.softmax()` para atención densa en producción.
   - Exigir el uso de `torch.nn.functional.scaled_dot_product_attention`, el cual invoca automáticamente los kernels fusionados en C++/CUDA de FlashAttention o Memory-Efficient Attention, reduciendo la complejidad de memoria de $\mathcal{O}(N^2)$ a $\mathcal{O}(N)$ y evitando desbordamientos de OOM en GPUs.
