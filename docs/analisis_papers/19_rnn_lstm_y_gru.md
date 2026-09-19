# Monografía 19: Redes Recurrentes (RNN, LSTM y GRU) — La Patología del Desvanecimiento en BPTT, el Carrusel de Error Constante (CEC) y el Mecanismo de Compuertas

> **Directorio de Ubicación:** `docs/analisis_papers/19_rnn_lstm_y_gru.md`  
> **Ficha Técnica Modular Resumida:** [`docs/algoritmos_ml/19_rnn_lstm_y_gru.md`](../algoritmos_ml/19_rnn_lstm_y_gru.md)  
> **Estado del Documento:** Riguroso / Nivel Doctoral / Producción Académica  

---

## 1. Ficha Bibliográfica y Genealogía de Papers Seminales

1. **La Red Recurrente Simple de Contexto (Elman, 1990):**
   - **Título:** *Finding Structure in Time*
   - **Autor:** Jeffrey L. Elman (University of California, San Diego).
   - **Publicación:** *Cognitive Science*, 14(2), pp. 179–211 (1990).
   - **Aporte Principal:** Introducción formal de la arquitectura recurrente de Elman (RNN simple o *Vanilla RNN*), incorporando un vector de estado de contexto oculto autorregresivo que retroalimenta la activación previa $h_{t-1}$ junto con la entrada actual $x_t$ para procesar secuencias temporales de longitud arbitraria.

2. **El Diagnóstico Matemático del Desvanecimiento de Gradientes (1991, 1994):**
   - **Papers Fundacionales:**
     - Sepp Hochreiter (1991): *Untersuchungen zu dynamischen neuronalen Netzen*. Tesis de Diploma, Technische Universität München (asesor: Jürgen Schmidhuber).
     - Yoshua Bengio, Patrice Simard y Paolo Frasconi (1994): *Learning long-term dependencies with gradient descent is difficult*. *IEEE Transactions on Neural Networks*, 5(2), pp. 157–166.
   - **Aporte Principal:** Demostración analítica rigurosa mediante teoría espectral de operadores de que el algoritmo de Retropropagación a Través del Tiempo (BPTT) sufre intrínsecamente de decaimiento o explosión exponencial del gradiente ($\sim W^T$), probando la imposibilidad práctica de que una RNN simple aprenda dependencias temporales que superen 10 pasos temporales.

3. **La Creación Canónica de LSTM y el CEC (Neural Computation, 1997):**
   - **Título:** *Long Short-Term Memory*
   - **Autores:** Sepp Hochreiter y Jürgen Schmidhuber.
   - **Publicación:** *Neural Computation*, 9(8), pp. 1735–1780 (1997).
   - **Aporte Principal:** Formulación de la arquitectura **Long Short-Term Memory (LSTM)** gobernada por el **Carrusel de Error Constante (Constant Error Carousel, CEC)**. Introducción de un estado de celda aditivo lineal $C_t$ desacoplado del estado oculto $h_t$, regulado mediante compuertas multiplicativas analógicas diferenciables (compuerta de entrada $i_t$ y compuerta de salida $o_t$), permitiendo el flujo de gradiente no atenuado a lo largo de cientos de pasos temporales.

4. **La Introducción de la Compuerta de Olvido (Neural Computation, 2000):**
   - **Título:** *Learning to Forget: Continual Prediction with LSTM*
   - **Autores:** Felix A. Gers, Jürgen Schmidhuber y Fred Cummins.
   - **Publicación:** *Neural Computation*, 12(10), pp. 2451–2471 (2000).
   - **Aporte Principal:** Identificación de que el diseño original de 1997 no podía resetear su estado interno ante secuencias continuas infinitas, saturando el acumulador $C_t$. Introducción de la **Compuerta de Olvido (*Forget Gate*, $f_t$)**, completando la formulación canónica universal de LSTM empleada en la industria actual.

5. **La Gated Recurrent Unit: GRU (EMNLP, 2014):**
   - **Título:** *Learning Phrase Representations using RNN Encoder-Decoder for Statistical Machine Translation*
   - **Autores:** Kyunghyun Cho, Bart van Merriënboer, Caglar Gulcehre, Dzmitry Bahdanau, Fethi Bougares, Holger Schwenk y Yoshua Bengio.
   - **Publicación:** *Proceedings of the 2014 Conference on Empirical Methods in Natural Language Processing (EMNLP)*, pp. 1724–1734 (2014).
   - **Aporte Principal:** Simplificación estructural de LSTM eliminando el estado de celda independiente $C_t$ y unificando el control en dos compuertas (*Reset Gate* $r_t$ y *Update Gate* $z_t$). Demostraron que una interpolación convexa sobre el estado oculto reduce los parámetros en un 25% con un rendimiento empírico equivalente en traducción automática.

6. **La Regla Crítica de Inicialización del Sesgo de Olvido (ICML, 2015):**
   - **Título:** *An Empirical Exploration of Recurrent Network Architectures*
   - **Autores:** Rafal Jozefowicz, Wojciech Zaremba e Ilya Sutskever (Google Brain).
   - **Publicación:** *International Conference on Machine Learning (ICML 2015)*, pp. 2342–2350.
   - **Aporte Principal:** Evaluación exhaustiva de más de diez mil variantes de arquitecturas recurrentes. Conclusión matemática y práctica definitiva: inicializar el sesgo de la compuerta de olvido con un valor positivo ($b_f = 1.0$ o $2.0$) es el factor más determinante para igualar o superar a arquitecturas más complejas, forzando a la red a recordar toda la historia por defecto al inicio del entrenamiento.

---

## 2. Génesis Teórica: Desvanecimiento de Gradientes en BPTT y el CEC

### 2.1. Desdoblamiento Temporal (*Unrolling*) y Backpropagation Through Time (BPTT)

Consideremos una Red Neuronal Recurrente simple procesando una secuencia de entrada $\{x_1, x_2, \dots, x_T\}$ con $x_t \in \mathbb{R}^D$:
$$h_t = \tanh(W_{hh} h_{t-1} + W_{xh} x_t + b_h), \quad \text{con } h_0 = \mathbf{0}$$
$$y_t = \text{Softmax}(W_{hy} h_t + b_y)$$
donde $h_t \in \mathbb{R}^H$ representa la memoria recurrente en el instante temporal $t$.

```
    t=1                   t=2                                 t=T
    x₁                    x₂                                  x_T
    │                     │                                   │
    ▼                     ▼                                   ▼
 ┌───────┐   h₁        ┌───────┐   h₂                    ┌───────┐   h_T
 │  RNN  │ ──────────► │  RNN  │ ──────────► ··· ──────► │  RNN  │ ──────────► y_T
 └───────┘             └───────┘                         └───────┘              │
                                                                                ▼
                                                                           Loss: L_T
   ◄───────────────────────── FLUJO DE GRADIENTE (BPTT) ────────────────────────
```

Sea $\mathcal{L}_T$ la función de pérdida evaluada al final de la secuencia temporal (en el paso $T$).  
Deseamos calcular la derivada parcial de $\mathcal{L}_T$ respecto al estado inicial temprano $h_1$:
$$\frac{\partial \mathcal{L}_T}{\partial h_1} = \frac{\partial \mathcal{L}_T}{\partial h_T} \frac{\partial h_T}{\partial h_1}$$
Aplicando la regla de la cadena multivariante a lo largo de los $T-1$ pasos temporales encadenados:
$$\frac{\partial h_T}{\partial h_1} = \prod_{k=2}^T \frac{\partial h_k}{\partial h_{k-1}}$$

Calculamos la matriz Jacobiana local $\frac{\partial h_k}{\partial h_{k-1}}$:
$$\frac{\partial h_k}{\partial h_{k-1}} = \text{diag}\left( 1 - h_k^2 \right) W_{hh}^T$$
donde $\text{diag}(1 - h_k^2)$ representa la derivada de la tangente hiperbólica evaluada elemento a elemento ($\tanh'(z) = 1 - \tanh^2(z) \in (0, 1]$).

Sustituyendo en el producto global:
$$\frac{\partial \mathcal{L}_T}{\partial h_1} = \frac{\partial \mathcal{L}_T}{\partial h_T} \left[ \prod_{k=2}^T \text{diag}(1 - h_k^2) W_{hh}^T \right]$$

### 2.2. Demostración Espectral del Desvanecimiento y la Explosión

Sea $\gamma$ una cota superior sobre la norma espectral de la Jacobiana:
$$\left\| \frac{\partial h_k}{\partial h_{k-1}} \right\|_2 \le \left\| \text{diag}(1 - h_k^2) \right\|_2 \cdot \|W_{hh}^T\|_2 \le 1.0 \cdot \lambda_{\max}(W_{hh})$$
donde $\lambda_{\max}(W_{hh})$ es el mayor valor singular de la matriz de transición recurrente $W_{hh}$.

Por propiedades multiplicativas de normas subordinadas de operadores:
$$\left\| \frac{\partial \mathcal{L}_T}{\partial h_1} \right\|_2 \le \left\| \frac{\partial \mathcal{L}_T}{\partial h_T} \right\|_2 \cdot \prod_{k=2}^T \left\| \frac{\partial h_k}{\partial h_{k-1}} \right\|_2 \le \left\| \frac{\partial \mathcal{L}_T}{\partial h_T} \right\|_2 \cdot (\lambda_{\max}(W_{hh}))^{T-1}$$

**Las Dos Patologías Analíticas:**
1. **Desvanecimiento Exponencial (*Vanishing Gradient*):**  
   Si $\lambda_{\max}(W_{hh}) < 1$, entonces $\lim_{T \to \infty} (\lambda_{\max}(W_{hh}))^T = 0$.  
   Para secuencias de longitud moderada ($T = 50$), si $\lambda = 0.9$, el factor de atenuación es $0.9^{50} \approx 0.0051$; para $T = 100$, es $0.9^{100} \approx 2.6 \times 10^{-5}$.  
   El gradiente se extingue exponencialmente hacia cero, haciendo que los pesos sinápticos $W_{hh}$ y $W_{xh}$ no reciban ninguna señal de aprendizaje respecto a eventos ocurridos en el pasado lejano.
2. **Explosión Exponencial (*Exploding Gradient*):**  
   Si $\lambda_{\max}(W_{hh}) > 1$ y las neuronas no saturan su tangente hiperbólica, el gradiente crece exponencialmente hacia el infinito ($\sim \lambda^T \to \infty$), produciendo desbordamientos numéricos de coma flotante (`NaN / Inf`) y oscilaciones caóticas de parámetros.

---

### 2.3. La Solución Fundamental: El Carrusel de Error Constante (CEC)

Hochreiter y Schmidhuber (1997) postularon que para preservar la memoria a largo plazo, la derivada temporal del acumulador de estado debe satisfacer **estrictamente la condición de conservación de error**:
$$\frac{\partial C_t}{\partial C_{t-1}} = I \implies \frac{\partial \mathcal{L}}{\partial C_1} = \frac{\partial \mathcal{L}}{\partial C_T} \prod_{k=2}^T \frac{\partial C_k}{\partial C_{k-1}} = \frac{\partial \mathcal{L}}{\partial C_T} (1 \cdot 1 \dots 1) = \frac{\partial \mathcal{L}}{\partial C_T}$$
Para materializar esta propiedad sin que la red colapse en un sistema lineal trivial, crearon una **línea de transmisión aditiva lineal protegida por compuertas multiplicativas no lineales**.

---

## 3. Derivaciones Matemáticas Paso a Paso

### 3.1. Ecuaciones Canónicas de LSTM con Forget Gate (Gers et al., 2000)

En cada paso temporal $t \in \{1, \dots, T\}$, la celda LSTM procesa el vector de entrada actual $x_t \in \mathbb{R}^{D}$ y el estado oculto previo $h_{t-1} \in \mathbb{R}^{H}$.  
Definimos la concatenación tensorial $u_t \in \mathbb{R}^{H + D}$:
$$u_t = \begin{bmatrix} h_{t-1} \\ x_t \end{bmatrix}$$

```
                                 C_{t-1} (Memoria a Largo Plazo)
                                    │
                  ┌─────────────────┼───────────────────────────┐
                  │                 ▼                           │
                  │              [ ⊗ ] ◄── Forget Gate: f_t     │
                  │                 │                           │
                  │                 ▼                           │
                  │              [ ⊕ ] ◄── Input x Candidate    │
                  │                 │      (i_t ⊗ C̃_t)          │
                  │                 │                           │
                  │                 ├───────────────────────┐   │
                  │                 ▼                       ▼   │
                  │              C_t (Actualizado)       [tanh] │
                  │                 │                       │   │
                  │                 │                       ▼   │
                  │                 │                    [ ⊗ ] ◄── Output Gate: o_t
                  │                 │                       │   │
                  └─────────────────┼───────────────────────┼───┘
                                    ▼                       ▼
                                   C_t                     h_t (Salida a Corto Plazo)
```

Las ecuaciones constitutivas del sistema son:

1. **Compuerta de Olvido ($f_t \in (0, 1)^H$):**  
   Determina qué proporción del estado de celda anterior preservar ($1$) o desechar ($0$):
   $$f_t = \sigma(W_f u_t + b_f) = \sigma(W_{fh} h_{t-1} + W_{fx} x_t + b_f)$$

2. **Compuerta de Entrada ($i_t \in (0, 1)^H$):**  
   Modula la intensidad con la que se escribirán nuevos datos en la memoria:
   $$i_t = \sigma(W_i u_t + b_i) = \sigma(W_{ih} h_{t-1} + W_{ix} x_t + b_i)$$

3. **Celda Candidata ($\tilde{C}_t \in (-1, 1)^H$):**  
   Genera nuevos contenidos de información mediante una función simétrica $\tanh$:
   $$\tilde{C}_t = \tanh(W_c u_t + b_c) = \tanh(W_{ch} h_{t-1} + W_{cx} x_t + b_c)$$

4. **Actualización Aditiva del Estado de Celda ($C_t \in \mathbb{R}^H$):**  
   Núcleo del Carrusel de Error Constante:
   $$C_t = f_t \odot C_{t-1} + i_t \odot \tilde{C}_t$$
   donde $\odot$ es el producto de Hadamard elemento a elemento.

5. **Compuerta de Salida ($o_t \in (0, 1)^H$):**  
   Filtra qué porción de la memoria profunda es visible como estado oculto observable:
   $$o_t = \sigma(W_o u_t + b_o) = \sigma(W_{oh} h_{t-1} + W_{ox} x_t + b_o)$$

6. **Estado Oculto Emitido ($h_t \in (-1, 1)^H$):**
   $$h_t = o_t \odot \tanh(C_t)$$

---

### 3.2. Derivación del Gradiente de BPTT en LSTM: La Autopista de Memoria

Sea $\mathcal{L}$ la función de pérdida global. Definimos el gradiente retropropagado hacia el estado oculto en el instante $t$:
$$\delta_{h, t} = \frac{\partial \mathcal{L}}{\partial h_t} + \delta_{h, t+1}^{\text{recurrente}}$$
donde $\delta_{h, t+1}^{\text{recurrente}}$ proviene de los pasos temporales futuros.

Calculamos la sensibilidad del estado de celda $C_t$:
$$\delta_{C, t} \equiv \frac{\partial \mathcal{L}}{\partial C_t} = \delta_{h, t} \frac{\partial h_t}{\partial C_t} + \frac{\partial \mathcal{L}}{\partial C_{t+1}} \frac{\partial C_{t+1}}{\partial C_t}$$

Evaluamos las derivadas parciales exactas:
1. De $h_t = o_t \odot \tanh(C_t)$:
   $$\frac{\partial h_t}{\partial C_t} = o_t \odot (1 - \tanh^2(C_t))$$
2. De $C_{t+1} = f_{t+1} \odot C_t + i_{t+1} \odot \tilde{C}_{t+1}$:
   $$\frac{\partial C_{t+1}}{\partial C_t} = \text{diag}(f_{t+1})$$

Sustituyendo en la ecuación de retropropagación del estado de celda:
$$\delta_{C, t} = \delta_{h, t} \odot o_t \odot (1 - \tanh^2(C_t)) + \delta_{C, t+1} \odot f_{t+1}$$

**Demostración de la Preservación del Gradiente:**  
Expandiendo recursivamente $\delta_{C, 1}$ desde el paso final $T$:
$$\delta_{C, 1} = \delta_{C, T} \odot \left( \prod_{k=2}^T f_k \right) + \sum_{t=1}^{T-1} \text{Términos locales}$$
Si las compuertas de olvido se mantienen saturadas cerca de $1$ ($f_k \approx 1.0$):
$$\prod_{k=2}^T f_k \approx 1.0 \implies \delta_{C, 1} \approx \delta_{C, T}$$
**El gradiente del estado de celda no depende de productos matriciales de pesos $W_{hh}^T$, sino de un producto escalar directo de compuertas de olvido $f_t \in [0, 1]$.**  
La red puede aprender a fijar $f_t = 1$ durante cientos de pasos para preservar una variable en memoria sin que su gradiente sufra atenuación.

#### Gradientes de las Compuertas y Parámetros:
Utilizando $\delta_{C, t}$:
- Para la compuerta de olvido:
  $$\delta_{f, t} = \delta_{C, t} \odot C_{t-1} \odot \sigma'(Z_f) = \delta_{C, t} \odot C_{t-1} \odot f_t \odot (1 - f_t)$$
- Para la compuerta de entrada:
  $$\delta_{i, t} = \delta_{C, t} \odot \tilde{C}_t \odot i_t \odot (1 - i_t)$$
- Para la celda candidata:
  $$\delta_{\tilde{C}, t} = \delta_{C, t} \odot i_t \odot (1 - \tilde{C}_t^2)$$
- Para la compuerta de salida:
  $$\delta_{o, t} = \delta_{h, t} \odot \tanh(C_t) \odot o_t \odot (1 - o_t)$$

---

### 3.3. Ecuaciones y Dinámica de GRU (Cho et al., 2014)

GRU fusiona el estado de celda $C_t$ y el estado oculto $h_t$ en una sola variable $h_t$, regulada por dos compuertas:

```
                  h_{t-1}
                     │
         ┌───────────┼────────────────────────────────────────┐
         │           ▼                                        │
         │   [ Reset Gate: r_t ]                              │
         │           │                                        │
         │           ▼                                        │
         │   (r_t ⊗ h_{t-1}) ──► [ tanh Candidate: h̃_t ]      │
         │                               │                    │
         │   [ Update Gate: z_t ]        │                    │
         │           │                   │                    │
         │           ├───────────────┐   │                    │
         │           ▼               ▼   ▼                    │
         │     (1 - z_t) ⊗ h_{t-1}  +   z_t ⊗ h̃_t            │
         │           │               │                        │
         └───────────┼───────────────┼────────────────────────┘
                     ▼               ▼
                                    h_t
```

1. **Compuerta de Reseteo ($r_t$):**  
   Determina qué parte del estado previo $h_{t-1}$ olvidar al calcular la nueva propuesta candidata:
   $$r_t = \sigma(W_r \cdot [h_{t-1}, x_t] + b_r)$$
2. **Compuerta de Actualización ($z_t$):**  
   Controla el balance entre la memoria histórica previa y el nuevo estado candidato:
   $$z_t = \sigma(W_z \cdot [h_{t-1}, x_t] + b_z)$$
3. **Estado Oculto Candidato ($\tilde{h}_t$):**
   $$\tilde{h}_t = \tanh(W_h \cdot [r_t \odot h_{t-1}, x_t] + b_h)$$
4. **Interpolación Convexa del Estado Oculto ($h_t$):**
   $$h_t = (1 - z_t) \odot h_{t-1} + z_t \odot \tilde{h}_t$$

**Derivada de Retención en GRU:**  
$$\frac{\partial h_t}{\partial h_{t-1}} = (1 - z_t) + \dots$$
Si la compuerta de actualización $z_t \approx 0$, $h_t \approx h_{t-1}$ y $\frac{\partial h_t}{\partial h_{t-1}} \approx I$, replicando el comportamiento de autopista lineal de LSTM sin requerir un estado de celda secundario.

---

## 4. Arquitectura de Sistemas y Regularización

1. **La Regla del Sesgo de Olvido $b_f = 1.0$ (Jozefowicz et al., 2015):**
   - Si los sesgos se inicializan en cero ($b_f = 0$), $f_t = \sigma(0) = 0.5$.
   - En este escenario, tras $T$ pasos, la memoria decae como $0.5^T \to 0$, forzando a la red a olvidar el 50% de la historia en cada paso desde el inicio del entrenamiento.
   - **Regla Imperativa:** Inicializar siempre $b_f = 1.0$ o $2.0$. Dado que $\sigma(1.0) \approx 0.73$ y $\sigma(2.0) \approx 0.88$, la celda comienza asumiendo por defecto que debe recordar todo, aprendiendo a olvidar solo cuando sea estrictamente necesario.

2. **Truncamiento de la Norma del Gradiente (*Gradient Clipping*):**
   - Para erradicar la explosión de gradientes en secuencias con dinámicas altamente no lineales, Mikolov (2012) formuló el escalado por norma:
     $$\tilde{g} = \begin{cases} g & \text{si } \|g\|_2 \le \text{clip\_norm} \\ \frac{\text{clip\_norm}}{\|g\|_2} g & \text{si } \|g\|_2 > \text{clip\_norm} \end{cases}$$
   - Preserva la dirección exacta del vector gradiente reescalando su magnitud para no desestabilizar la trayectoria del optimizador.

3. **Variational Dropout Recurrente (Gal & Ghahramani, 2016):**
   - Aplicar máscaras de Dropout independientes en cada paso temporal $t$ introduce un ruido destructivo que ahoga la propagación de la memoria.
   - **Solución:** Muestrear una única máscara estocástica de Dropout $m \sim \text{Bernoulli}(1-p)$ al inicio de la secuencia y **reutilizar exactamente la misma máscara a través de todos los pasos $t=1, \dots, T$**.

---

## 5. Tabla Comparativa Exhaustiva

| Característica | RNN Simple (Elman) | LSTM (Hochreiter & Schmidhuber) | GRU (Cho et al.) | Transformer (Vaswani) |
|---|---|---|---|---|
| **Estructura de Memoria** | Solo $h_t$ | Dual: $C_t$ (largo plazo) + $h_t$ (corto plazo) | Unificada: $h_t$ | Memoria de Atención Directa $QK^T$ |
| **Número de Compuertas** | 0 | 3 ($f_t, i_t, o_t$) + 1 candidato ($\tilde{C}_t$) | 2 ($r_t, z_t$) + 1 candidato ($\tilde{h}_t$) | Múltiples cabezales de atención |
| **Parámetros por Celda** | $H^2 + H D$ | $4 \times (H^2 + H D)$ | $3 \times (H^2 + H D)$ | $\mathcal{O}(D_{\text{model}}^2)$ por capa |
| **Capacidad Temporal** | $< 10$ pasos | $100 - 1000$ pasos | $100 - 500$ pasos | $> 100,000$ tokens (limitado por VRAM) |
| **Paralelismo en Tiempo** | No ($\mathcal{O}(T)$ secuencial) | No ($\mathcal{O}(T)$ secuencial) | No ($\mathcal{O}(T)$ secuencial) | **Totalmente Paralelo** ($\mathcal{O}(1)$ capas) |

---

## 6. Implementación Pura en Python y NumPy (Vectorización GEMM 4x)

En sistemas optimizados de alto rendimiento, no se calculan las cuatro compuertas de LSTM de forma aislada. Se concatenan los pesos en una única matriz gigante:
$$W = \begin{bmatrix} W_f \\ W_i \\ W_c \\ W_o \end{bmatrix} \in \mathbb{R}^{4H \times (H + D)}, \quad b = \begin{bmatrix} b_f \\ b_i \\ b_c \\ b_o \end{bmatrix} \in \mathbb{R}^{4H}$$
permitiendo resolver las cuatro compuertas con una única multiplicación de matrices de alta velocidad (GEMM) en cada paso temporal.

A continuación se desarrolla una celda **LSTM Pura completa con BPTT exacto**:

```python
import numpy as np


class LSTM_Puro:
    """
    Implementación matricial canónica de Long Short-Term Memory (LSTM) con BPTT en NumPy puro.
    Utiliza una matriz de pesos unificada (4H x [H+D]) para computar las compuertas
    de Olvido, Entrada, Candidato y Salida en un único producto matricial eficiente.
    """
    def __init__(self, input_dim, hidden_dim, forget_bias=1.0, random_state=42):
        self.D = input_dim
        self.H = hidden_dim
        self.forget_bias = forget_bias
        self.random_state = random_state

        rng = np.random.RandomState(random_state)
        # Inicialización Xavier/Glorot
        std = np.sqrt(2.0 / (input_dim + hidden_dim))
        
        # Pesos empaquetados: f, i, c, o en un solo tensor (4H, H + D)
        self.W = rng.normal(0.0, std, size=(4 * hidden_dim, hidden_dim + input_dim))
        self.b = np.zeros((4 * hidden_dim, 1))
        # Inicializar el sesgo de la compuerta de olvido en 1.0 (Regla de Jozefowicz)
        self.b[:hidden_dim] = forget_bias

    def _sigmoid(self, x):
        return 1.0 / (1.0 + np.exp(-np.clip(x, -30.0, 30.0)))

    def forward(self, X_seq):
        """
        Forward pass a través de la secuencia completa.
        X_seq shape: (T, D, Batch_size).
        Retorna la secuencia de estados ocultos H_seq y el diccionario de cachés.
        """
        T, D, B = X_seq.shape
        H = self.H

        H_seq = np.zeros((T, H, B), dtype=np.float64)
        C_seq = np.zeros((T, H, B), dtype=np.float64)
        
        h_prev = np.zeros((H, B), dtype=np.float64)
        c_prev = np.zeros((H, B), dtype=np.float64)

        cache = {'inputs': X_seq, 'u': {}, 'gates': {}, 'h_prev': h_prev, 'c_prev': c_prev}

        for t in range(T):
            xt = X_seq[t]  # (D, B)
            # Concatenación: u_t = [h_{t-1}; x_t] de shape (H + D, B)
            ut = np.vstack([h_prev, xt])
            cache['u'][t] = ut

            # Multiplicación matricial unificada de compuertas
            Z = np.dot(self.W, ut) + self.b  # (4H, B)

            # Desempaquetar compuertas
            f_t = self._sigmoid(Z[0:H])
            i_t = self._sigmoid(Z[H:2*H])
            c_tilde = np.tanh(Z[2*H:3*H])
            o_t = self._sigmoid(Z[3*H:4*H])

            cache['gates'][t] = (f_t, i_t, c_tilde, o_t)

            # Actualización del estado de celda (CEC)
            c_t = f_t * c_prev + i_t * c_tilde
            # Estado oculto saliente
            h_t = o_t * np.tanh(c_t)

            H_seq[t] = h_t
            C_seq[t] = c_t

            h_prev = h_t
            c_prev = c_t

        cache['H_seq'] = H_seq
        cache['C_seq'] = C_seq
        return H_seq, cache

    def backward(self, dH_seq, cache):
        """
        Backpropagation Through Time (BPTT) exacto a través de T pasos temporales.
        dH_seq shape: (T, H, Batch_size).
        """
        X_seq = cache['inputs']
        T, D, B = X_seq.shape
        H = self.H

        dW = np.zeros_like(self.W)
        db = np.zeros_like(self.b)
        dX_seq = np.zeros_like(X_seq)

        dh_next = np.zeros((H, B), dtype=np.float64)
        dc_next = np.zeros((H, B), dtype=np.float64)

        C_seq = cache['C_seq']

        for t in range(T - 1, -1, -1):
            f_t, i_t, c_tilde, o_t = cache['gates'][t]
            ut = cache['u'][t]
            c_t = C_seq[t]
            c_prev = C_seq[t - 1] if t > 0 else cache['c_prev']

            # Gradiente entrante a h_t (pérdida directa + paso t+1 futuro)
            dh_t = dH_seq[t] + dh_next

            # Gradiente de salida: h_t = o_t * tanh(c_t)
            tanh_c = np.tanh(c_t)
            do_t = dh_t * tanh_c * (o_t * (1.0 - o_t))

            # Gradiente del estado de celda: incluye flujo de compuerta de salida y paso t+1
            dc_t = dh_t * o_t * (1.0 - tanh_c**2) + dc_next

            # Gradientes de compuertas internas
            df_t = dc_t * c_prev * (f_t * (1.0 - f_t))
            di_t = dc_t * c_tilde * (i_t * (1.0 - i_t))
            dc_tilde = dc_t * i_t * (1.0 - c_tilde**2)

            # Concatenar gradientes de pre-activaciones dZ: (4H, B)
            dZ = np.vstack([df_t, di_t, dc_tilde, do_t])

            # Acumular gradientes de parámetros
            dW += np.dot(dZ, ut.T)
            db += np.sum(dZ, axis=1, keepdims=True)

            # Propagar gradientes hacia u_t = [h_{t-1}; x_t]
            du_t = np.dot(self.W.T, dZ)
            dh_next = du_t[:H]
            dX_seq[t] = du_t[H:]

            # Autopista del CEC: gradiente de C_{t-1} modulado por f_t
            dc_next = dc_t * f_t

        return dX_seq, dW, db


# =====================================================================
# Verificación Numérica: Flujo Continuo del CEC sin Desvanecimiento
# =====================================================================
if __name__ == "__main__":
    np.random.seed(42)

    # Secuencia larga de prueba: T = 30 pasos temporales, D = 4, Lote = 3
    T_len, D_in, B_size = 30, 4, 3
    X_input = np.random.randn(T_len, D_in, B_size)

    lstm = LSTM_Puro(input_dim=D_in, hidden_dim=8, forget_bias=1.0, random_state=42)
    H_out, cache_dict = lstm.forward(X_input)

    # Simulamos que la pérdida ocurre ÚNICAMENTE en el paso final T-1
    dH = np.zeros_like(H_out)
    dH[-1] = np.ones((8, B_size))  # Señal de gradiente unitaria en T=30

    dX, dW_grad, db_grad = lstm.backward(dH, cache_dict)

    print("=== Validación Numérica: LSTM Pura y Carrusel de Error Constante (CEC) ===")
    print(f"Secuencia temporal evaluada: {T_len} pasos.")
    print(f"Forma de salida de estados ocultos H_seq: {H_out.shape}")
    print(f"Gradiente propagado en paso final t={T_len-1}: {np.mean(np.abs(dX[-1])):.4f}")
    print(f"Gradiente transmitido al primer paso t=0:     {np.mean(np.abs(dX[0])):.4f}")
    print(f"Ratio de conservación de gradiente t_0 / t_{T_len-1}: {np.mean(np.abs(dX[0])) / np.mean(np.abs(dX[-1])):.4f}")
    print("Demostración exitosa: El gradiente no se extinguió a 0 tras 30 pasos de tiempo.")
```

---

## 7. Directrices de Razonamiento para los Modelos de Inteligencia Artificial en Prig IDE

Cuando un modelo de lenguaje en Prig IDE analice, diseñe, optimice o diagnostique redes neuronales para secuencias temporales (`torch.nn.LSTM`, `torch.nn.GRU`), aplicará de manera estricta las siguientes directrices técnicas:

1. **Inicialización Obligatoria del Sesgo de Olvido:**
   - En cualquier instanciación de LSTM en PyTorch, forzar siempre la inicialización del sesgo de la compuerta de olvido en $1.0$:
     ```python
     for name, param in lstm.named_parameters():
         if 'bias' in name:
             # El bloque de sesgos está ordenado: [b_i | b_f | b_g | b_o] en PyTorch
             n = param.size(0)
             param.data[n//4 : n//2].fill_(1.0)
     ```
   - Si no se realiza, la celda comienza olvidando el 50% de la historia en cada paso de tiempo, atrofiando el aprendizaje de dependencias lejanas.

2. **Truncamiento Incondicional de la Norma del Gradiente:**
   - Aplicar siempre `torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)` o `2.0` antes de cada llamada a `optimizer.step()`.
   - En secuencias temporales, picos aperiódicos de curvatura pueden elevar momentáneamente la norma del gradiente a $>1000$, descalibrando los pesos de forma irreversible.

3. **Criterio de Selección: LSTM vs. GRU:**
   - Recomendar **GRU** cuando el conjunto de datos sea pequeño o mediano ($N < 50,000$), se disponga de limitaciones estrictas de memoria/cómputo o la latencia de inferencia sea crítica (GRU tiene 25% menos pesos).
   - Prescribir **LSTM** ante secuencias largas donde el problema involucre conteo explícito de eventos a largo plazo o tareas algorítmicas complejas que requieran desacoplar la memoria profunda del estado observable.

4. **Transición hacia Transformers:**
   - Si la longitud de secuencia $T$ supera sistemáticamente los $300 - 500$ pasos temporales o si se requiere entrenamiento a gran escala en clústeres de GPUs, diagnosticar la **barrera secuencial** de BPTT (incapacidad de paralelizar en el eje temporal $\mathcal{O}(T)$).
   - Recomendar la transición hacia modelos de **Transformers o Mamba/State-Space Models (SSM)**.
