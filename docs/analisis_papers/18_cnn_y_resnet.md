# Monografía 18: Redes Convolucionales (CNN) y Bloques Residuales (ResNet) — Equivarianza a la Traslación, la Paradoja de la Degradación y la Autopista de Gradientes

> **Directorio de Ubicación:** `docs/analisis_papers/18_cnn_y_resnet.md`  
> **Ficha Técnica Modular Resumida:** [`docs/algoritmos_ml/18_cnn_y_resnet.md`](../algoritmos_ml/18_cnn_y_resnet.md)  
> **Estado del Documento:** Riguroso / Nivel Doctoral / Producción Académica  

---

## 1. Ficha Bibliográfica y Genealogía de Papers Seminales

1. **La Génesis Neurobiológica: El Neocognitrón (1980):**
   - **Título:** *Neocognitron: A self-organizing neural network model for a mechanism of pattern recognition unaffected by shift in position*
   - **Autor:** Kunihiko Fukushima (NHK Broadcasting Science Research Laboratories).
   - **Publicación:** *Biological Cybernetics*, 36(4), pp. 193–202 (1980).
   - **Aporte Principal:** Inspirado en los descubrimientos neurofisiológicos de David Hubel y Torsten Wiesel (Premio Nobel 1981) sobre la corteza visual primaria de los felinos, introdujo la alternancia jerárquica entre células simples (extracción de características locales con campos receptivos definidos) y células complejas (tolerancia a desplazamientos espaciales y pooling).

2. **LeNet-5 y el Aprendizaje Basado en Gradientes (1989, 1998):**
   - **Papers Fundacionales:**
     - Yann LeCun et al. (1989): *Backpropagation applied to handwritten zip code recognition*. *Neural Computation*, 1(4), pp. 541–551.
     - Yann LeCun, Léon Bottou, Yoshua Bengio y Patrick Haffner (1998): *Gradient-Based Learning Applied to Document Recognition*. *Proceedings of the IEEE*, 86(11), pp. 2278–2324.
   - **Aporte Principal:** Formalización analítica moderna de las Redes Convolucionales (CNN). Introducción del principio de **compartición de pesos** (*weight sharing*) e invariancia traslacional mediante convolución discreta 2D entrenada extremo a extremo vía retropropagación para el reconocimiento de dígitos manuscritos (MNIST).

3. **El Punto de Inflexión de la Visión Computacional: AlexNet (NeurIPS, 2012):**
   - **Título:** *ImageNet Classification with Deep Convolutional Neural Networks*
   - **Autores:** Alex Krizhevsky, Ilya Sutskever y Geoffrey E. Hinton (University of Toronto).
   - **Publicación:** *Advances in Neural Information Processing Systems (NeurIPS 2012)*, 25, pp. 1097–1105.
   - **Aporte Principal:** Victoria categórica en ImageNet (reducción del top-5 error del 26% al 15.3%), desatando la era dorada del Deep Learning contemporáneo. Claves arquitectónicas: implementación masivamente paralela en GPUs NVIDIA con CUDA, adopción de la activación no saturante **ReLU**, técnica de regularización estocástica **Dropout** y aumento sintético de datos (*Data Augmentation*).

4. **Factorización Espacial y Profundidad Homogénea: VGG (ICLR, 2015):**
   - **Título:** *Very Deep Convolutional Networks for Large-Scale Image Recognition*
   - **Autores:** Karen Simonyan y Andrew Zisserman (Visual Geometry Group, University of Oxford).
   - **Publicación:** *International Conference on Learning Representations (ICLR 2015)* (arXiv:1409.1556).
   - **Aporte Principal:** Demostración analítica de que una secuencia de dos capas convolucionales con filtros pequeños de $3 \times 3$ tiene el mismo campo receptivo efectivo que un filtro de $5 \times 5$, pero utiliza $2 \times (3^2 C^2) = 18 C^2$ parámetros frente a $25 C^2$ (28% menos pesos) e incorpora el doble de no linealidades discriminantes.

5. **El Manifiesto de ResNet: Conexiones Residuales (CVPR, 2016 — Best Paper Award):**
   - **Título:** *Deep Residual Learning for Image Recognition*
   - **Autores:** Kaiming He, Xiangyu Zhang, Shaoqing Ren y Jian Sun (Microsoft Research).
   - **Publicación:** *IEEE Conference on Computer Vision and Pattern Recognition (CVPR 2016)*, pp. 770–778 (arXiv:1512.03385).
   - **Aporte Principal:** Identificación y solución matemática a la **paradoja de degradación** en redes ultra-profundas. Introducción de los enlaces de salto (*skip connections*) con mapeos de identidad $y = \mathcal{F}(x) + x$, permitiendo entrenar de manera estable redes de 50, 101 y hasta 152 capas (superando por primera vez el nivel de precisión humana en ImageNet con 3.57% de error).

6. **Mapeos de Identidad y Autopista Pura de Gradientes (ECCV, 2016):**
   - **Título:** *Identity Mappings in Deep Residual Networks*
   - **Autores:** Kaiming He, Xiangyu Zhang, Shaoqing Ren y Jian Sun.
   - **Publicación:** *European Conference on Computer Vision (ECCV 2016)*, pp. 630–645.
   - **Aporte Principal:** Análisis matemático de la propagación aditiva sin obstáculos. Reformulación de la arquitectura residual a la variante *Pre-Activation* (colocando BatchNorm y ReLU antes del kernel convolucional), garantizando que el gradiente fluya directamente a través del enlace de identidad hacia capas arbitrariamente tempranas sin sufrir distorsiones no lineales.

---

## 2. Génesis Teórica: Inductive Biases Espaciales y la Paradoja de la Degradación

### 2.1. La Falla Estructural de los Perceptrones Densos en Imágenes

Sea una imagen en escala de grises de resolución modesta $256 \times 256$ ($D = 65,536$ píxeles).  
Si conectamos esta entrada a una capa densa oculta de $1,000$ neuronas:
$$\text{Parámetros} = 65,536 \times 1,000 \approx 6.55 \times 10^7 \text{ pesos sinápticos}$$
Para imágenes RGB a color en alta definición ($1024 \times 1024 \times 3$), una sola capa densa requeriría más de $3 \times 10^9$ parámetros, provocando sobreajuste catastrófico e imposibilidad de cómputo en hardware moderno.

Más grave aún es la ausencia de **sesgo inductivo geométrico (*Inductive Bias*)**:
- Un Perceptrón Denso aplana la imagen en un vector 1D, destruyendo la adyacencia métrica euclidiana entre píxeles vecinos.
- Si un gato aparece en la esquina superior izquierda de la imagen, la red densa aprende pesos para esa región espacial; si el mismo gato se desplaza a la esquina inferior derecha, la red monocapa es completamente ciega al patrón y requiere aprenderlo desde cero.

### 2.2. Los Tres Pilares de la Convolución 2D
1. **Conectividad Local (*Local Receptive Fields*):** Cada neurona se conecta únicamente a una pequeña ventana espacial de tamaño $k_h \times k_w$ (típicamente $3 \times 3$), explotando la correlación local de píxeles.
2. **Compartición de Pesos (*Weight Sharing*):** El mismo banco de filtros se desliza uniformemente a lo largo de toda la matriz espacial, reduciendo el número de parámetros a $C_{out} \times C_{in} \times k_h \times k_w$, independiente de la resolución $(H, W)$ de la imagen.
3. **Equivarianza a la Traslación:** Sea $T_g$ un operador de desplazamiento espacial. La operación de convolución conmuta estrictamente con la traslación:
   $$\text{Conv}(T_g(X)) = T_g(\text{Conv}(X))$$

```
   Perceptrón Multicapa (Denso)                    Capa Convolucional 2D (Filtro 3x3)
  ┌─────────────────────────────────────┐         ┌─────────────────────────────────────┐
  │ Cada neurona se conecta con TODOS   │         │ Conectividad local y pesos          │
  │ los píxeles (HW × HW parámetros).   │         │ compartidos (solo 3x3 = 9 pesos     │
  │ Sin concepto de contigüidad espacial│         │ por canal, independientes de HW).   │
  └──────────────────┬──────────────────┘         └──────────────────┬──────────────────┘
                     │                                               │
                     ▼                                               ▼
         Inviable en Imágenes                          Equivarianza Traslacional
         y Propenso a Overfitting                       y Eficiencia de Parámetros
```

---

### 2.3. La Paradoja de la Degradación en Redes Profundas (*The Degradation Problem*)

Hacia 2015, con la introducción de la inicialización He Normal y Batch Normalization, el problema del desvanecimiento/explosión exponencial de gradientes en la inicialización estaba bajo control analítico. Sin embargo, al intentar construir redes convolucionales más profundas apilando capas convencionales (*Plain Networks*), los investigadores observaron un fenómeno desconcertante:

```
                  Error de Entrenamiento (%) en Plain Networks (He et al., 2016)
               50 │
                  │             Plain-56 (56 capas) ──► Mayor error de entrenamiento
               40 │          /‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾
                  │         /
               30 │        /   Plain-20 (20 capas) ──► Menor error de entrenamiento
                  │       /  /‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾
               20 │      /  /
                  └─────┴──┴────────────────────────► Épocas de Entrenamiento
```

**Demostración de que la Degradación NO es Sobreajuste (*Overfitting*):**  
Si el problema fuera sobreajuste, la red de 56 capas alcanzaría un error de entrenamiento nulo o muy bajo y exhibiría un error de prueba elevado.  
Sin embargo, **la red más profunda exhibe un error de entrenamiento considerablemente superior a la red poco profunda**.  
Por teoría de optimización, un modelo más profundo contiene dentro de su espacio de hipótesis a todos los modelos menos profundos: basta con que las 36 capas adicionales aprendan la **función identidad** ($\mathcal{H}(x) = x$) para que la red profunda replique exactamente el rendimiento de la red de 20 capas.  
El hecho de que el optimizador SGD sea incapaz de encontrar esta solución demuestra que **aproximar la identidad mediante composiciones sucesivas de capas no lineales $\sigma(W_2 \sigma(W_1 x + b_1) + b_2)$ es una tarea numéricamente intratable para los algoritmos basados en gradiente**.

---

## 3. Derivaciones Matemáticas Paso a Paso

### 3.1. Operación Convolucional 2D Discreta y Dimensiones Espaciales

Sea el tensor de entrada $X \in \mathbb{R}^{B \times C_{in} \times H_{in} \times W_{in}}$ y un banco de filtros convolucionales $W \in \mathbb{R}^{C_{out} \times C_{in} \times k_h \times k_w}$ con sesgo $b \in \mathbb{R}^{C_{out}}$.  
Para una muestra individual en el lote, canal de salida $c_{out}$ y coordenadas espaciales $(i, j)$:
$$Y(c_{out}, i, j) = b(c_{out}) + \sum_{c_{in}=1}^{C_{in}} \sum_{m=0}^{k_h - 1} \sum_{n=0}^{k_w - 1} X(c_{in}, i \cdot s + m - p, j \cdot s + n - p) \, W(c_{out}, c_{in}, m, n)$$
donde:
- $s$ es el paso de desplazamiento (*stride*).
- $p$ es el margen de relleno con ceros (*padding*).

#### Fórmula Analítica de Dimensiones Espaciales:
$$H_{out} = \left\lfloor \frac{H_{in} - k_h + 2p}{s} \right\rfloor + 1$$
$$W_{out} = \left\lfloor \frac{W_{in} - k_w + 2p}{s} \right\rfloor + 1$$
Si se selecciona *padding unitario simétrico* ($p = \lfloor k / 2 \rfloor$) con $k=3$ y stride $s=1$:
$$H_{out} = \frac{H_{in} - 3 + 2(1)}{1} + 1 = H_{in}$$
las dimensiones espaciales se preservan intactas (*Same Padding*).

---

### 3.2. Derivación Rigurosa de Backpropagation para Convolución 2D

Sea $\mathcal{L}$ la función de pérdida escalar y consideremos el tensor de sensibilidad aguas arriba:
$$\delta_{out} \equiv \frac{\partial \mathcal{L}}{\partial Y} \in \mathbb{R}^{C_{out} \times H_{out} \times W_{out}}$$

#### 1. Gradiente Respecto a los Filtros Convolucionales ($\frac{\partial \mathcal{L}}{\partial W}$):
Aplicando la regla de la cadena multivariante sobre cada peso del kernel $W(c_{out}, c_{in}, m, n)$:
$$\frac{\partial \mathcal{L}}{\partial W(c_{out}, c_{in}, m, n)} = \sum_{i=0}^{H_{out}-1} \sum_{j=0}^{W_{out}-1} \frac{\partial \mathcal{L}}{\partial Y(c_{out}, i, j)} \frac{\partial Y(c_{out}, i, j)}{\partial W(c_{out}, c_{in}, m, n)}$$
Dado que $\frac{\partial Y(c_{out}, i, j)}{\partial W(c_{out}, c_{in}, m, n)} = X(c_{in}, i \cdot s + m, j \cdot s + n)$:
$$\frac{\partial \mathcal{L}}{\partial W(c_{out}, c_{in}, m, n)} = \sum_{i=0}^{H_{out}-1} \sum_{j=0}^{W_{out}-1} \delta_{out}(c_{out}, i, j) \cdot X(c_{in}, i \cdot s + m, j \cdot s + n)$$
**Interpretación Formal:**  
El gradiente respecto al kernel es la **convolución cruzada** entre el tensor de entrada original $X$ y el tensor de errores retropropagados $\delta_{out}$.

#### 2. Gradiente Respecto a la Entrada ($X$):
Para propagar el error hacia la capa previa ($\delta_{in} = \frac{\partial \mathcal{L}}{\partial X}$):
$$\frac{\partial \mathcal{L}}{\partial X(c_{in}, i', j')} = \sum_{c_{out}=1}^{C_{out}} \sum_{m, n} \delta_{out}(c_{out}, i, j) W(c_{out}, c_{in}, m, n)$$
donde $i' = i \cdot s + m \implies m = i' - i \cdot s$.  
Esta operación equivale matemáticamente a la **convolución completa (*Full Convolution*)** del tensor de error $\delta_{out}$ con el filtro rotado espacialmente $180^\circ$ ($\text{rot}_{180}(W)$).

---

### 3.3. La Matemática del Bloque Residual: Formulación y Autopista de Gradientes

En lugar de intentar que las capas convolucionales intermedias ajusten directamente el mapeo objetivo subyacente $\mathcal{H}(x)$, He et al. parametrizan las capas para que aprendan la **función residual**:
$$\mathcal{F}(x) \equiv \mathcal{H}(x) - x \implies \mathcal{H}(x) = \mathcal{F}(x, \{W_i\}) + x$$

```
                         x (Tensor de Entrada)
                         │
            ┌────────────┴────────────┐
            │                         │ (Conexión de Identidad / Skip)
            ▼                         │
     [ Weight Layer ]                 │
            │                         │
            ▼                         │
        [ ReLU ]                      │
            │                         │
            ▼                         │
     [ Weight Layer ]                 │
            │                         │
            ▼                         │
          F(x)                        │
            │                         │
            └────────────► ➕ ◄───────┘
                           │
                           ▼
                    ReLU( F(x) + x )
```

#### Teorema del Flujo Aditivo de Gradientes en Redes Residuales

Consideremos una red compuesta por $L$ bloques residuales encadenados.  
Para el bloque $l$:
$$x_{l+1} = x_l + \mathcal{F}(x_l, \mathcal{W}_l)$$
donde $x_l$ es la entrada al bloque y $\mathcal{F}$ representa las transformaciones no lineales convolucionales.

Por inducción matemática, podemos expresar la activación de cualquier capa profunda $L$ en función directa de cualquier capa temprana $l < L$:
$$x_{l+2} = x_{l+1} + \mathcal{F}(x_{l+1}, \mathcal{W}_{l+1}) = x_l + \mathcal{F}(x_l, \mathcal{W}_l) + \mathcal{F}(x_{l+1}, \mathcal{W}_{l+1})$$
Generalizando para $L$:
$$x_L = x_l + \sum_{i=l}^{L-1} \mathcal{F}(x_i, \mathcal{W}_i)$$

**Propiedad 1: Representación Aditiva Global.**  
La salida de una capa profunda $x_L$ no es una composición recursiva multiplicativa de funciones $\mathcal{F}_{L-1}(\mathcal{F}_{L-2}(\dots))$, sino una **suma directa de la entrada original $x_l$ más los residuos calculados por todos los bloques intermedios**.

**Propiedad 2: Derivación de la Autopista de Gradientes (*Gradient Highway*).**  
Sea $\mathcal{E}$ la función de error escalar al final de la red.  
Calculamos la derivada parcial de $\mathcal{E}$ respecto a la activación temprana $x_l$ aplicando la regla de la cadena multivariante:
$$\frac{\partial \mathcal{E}}{\partial x_l} = \frac{\partial \mathcal{E}}{\partial x_L} \frac{\partial x_L}{\partial x_l} = \frac{\partial \mathcal{E}}{\partial x_L} \frac{\partial}{\partial x_l} \left[ x_l + \sum_{i=l}^{L-1} \mathcal{F}(x_i, \mathcal{W}_i) \right]$$
Diferenciando el término de identidad $\frac{\partial x_l}{\partial x_l} = I$:
$$\frac{\partial \mathcal{E}}{\partial x_l} = \frac{\partial \mathcal{E}}{\partial x_L} \left( I + \frac{\partial}{\partial x_l} \sum_{i=l}^{L-1} \mathcal{F}(x_i, \mathcal{W}_i) \right) = \underbrace{\frac{\partial \mathcal{E}}{\partial x_L}}_{\text{Flujo Directo no Atenuado}} + \underbrace{\frac{\partial \mathcal{E}}{\partial x_L} \left( \frac{\partial}{\partial x_l} \sum_{i=l}^{L-1} \mathcal{F}(x_i, \mathcal{W}_i) \right)}_{\text{Flujo Modulado por Pesos}}$$

#### Implicaciones Fundamentales del Gradiente Residual:
1. **Inmunidad al Desvanecimiento Exponencial:**  
   En redes planas convencionales, el gradiente temprano depende de un producto matricial continuo: $\frac{\partial \mathcal{E}}{\partial x_l} = \frac{\partial \mathcal{E}}{\partial x_L} \prod_{i=l}^{L-1} W_i^T \sigma'$. Si las normas de los pesos son menores a 1, el gradiente decae exponencialmente a cero ($\sim 0^L$).  
   En ResNet, el término $I$ garantiza que **el gradiente $\frac{\partial \mathcal{E}}{\partial x_L}$ se transmite de manera limpia e íntegra a cualquier bloque anterior $x_l$**, sin importar si $L = 1000$.
2. **Imposibilidad de Anulación Sistemática:**  
   Para que el gradiente total $\frac{\partial \mathcal{E}}{\partial x_l}$ se anule, el término multiplicativo entre paréntesis debería ser exactamente igual a $-1$ para todas las muestras del lote:
   $$\frac{\partial}{\partial x_l} \sum_{i=l}^{L-1} \mathcal{F}(x_i, \mathcal{W}_i) = -I$$
   lo cual es estadísticamente imposible en regímenes estocásticos de optimización.

---

### 3.4. Topologías Residuales: BasicBlock vs. Bottleneck

```
        BasicBlock (ResNet-18/34)                         Bottleneck (ResNet-50/101/152)
       ┌─────────────────────────┐                      ┌─────────────────────────────┐
       │   x ∈ ℝ^(C × H × W)     │                      │      x ∈ ℝ^(C × H × W)      │
       └────────────┬────────────┘                      └──────────────┬──────────────┘
                    │                                                  │
       ┌────────────┴────────────┐                      ┌──────────────┴──────────────┐
       │ Conv2D (3x3, C canales) │                      │ Conv2D (1x1, C/4 canales)   │ ◄── Reducción
       │ BatchNorm + ReLU        │                      │ BatchNorm + ReLU            │
       ├─────────────────────────┤                      ├─────────────────────────────┤
       │ Conv2D (3x3, C canales) │                      │ Conv2D (3x3, C/4 canales)   │ ◄── Procesamiento
       │ BatchNorm               │                      │ BatchNorm + ReLU            │
       └────────────┬────────────┘                      ├─────────────────────────────┤
                    │                                   │ Conv2D (1x1, C canales)     │ ◄── Expansión
                    │                                   │ BatchNorm                   │
                    ▼                                   └──────────────┬──────────────┘
            ➕ (x + F(x))                                              ▼
                    │                                           ➕ (x + F(x))
                    ▼                                                  │
                  ReLU                                                 ▼
                                                                     ReLU
```

**Ventaja Computacional del Cuello de Botella (*Bottleneck*):**  
En un BasicBlock de 256 canales, dos capas de $3 \times 3$ consumen:
$$\text{Operaciones} \sim 2 \times (3 \times 3 \times 256 \times 256) \approx 1,179,648 \text{ multiplicaciones por píxel}$$
En un Bottleneck con factor de compresión 4 (reduciendo a 64 canales):
$$\text{Conv } 1\times 1: 1 \times 1 \times 256 \times 64 = 16,384$$
$$\text{Conv } 3\times 3: 3 \times 3 \times 64 \times 64 = 36,864$$
$$\text{Conv } 1\times 1: 1 \times 1 \times 64 \times 256 = 16,384$$
$$\text{Total} = 16,384 + 36,864 + 16,384 = 69,632 \text{ operaciones}$$
El diseño Bottleneck reduce el coste computacional en un **factor de 17x**, permitiendo entrenar ResNet-50, 101 y 152 con presupuestos de cómputo comparables a redes de 34 capas.

---

## 4. Arquitectura de Sistemas y Evolución

1. **Global Average Pooling (Lin, Chen & Yan, 2013):**
   - Reemplaza las gigantescas capas densas terminales de AlexNet/VGG (que acumulaban más del 80% de los parámetros del modelo) mediante un promedio espacial directo:
     $$\text{GAP}(c) = \frac{1}{H \times W} \sum_{i=1}^H \sum_{j=1}^W A(c, i, j)$$
   - Conecta directamente el tensor de canales con las categorías finales mediante una única matriz lineal pequeña $C \times \text{num\_classes}$, erradicando el riesgo de sobreajuste estructural.

2. **Alineación de Dimensiones en la Conexión de Identidad:**
   - Cuando el bloque residual aplica un stride $s=2$ o expande el número de canales ($C_{out} > C_{in}$), la suma simple $x + \mathcal{F}(x)$ es inviable por discrepancia tensorial.
   - ResNet resuelve esto proyectando la rama de salto mediante una **convolución $1 \times 1$ con stride 2 y BatchNorm**:
     $$x_{\text{proj}} = \text{BatchNorm}(\text{Conv}_{1 \times 1}(x, \text{stride}=2)) \implies y = \mathcal{F}(x) + x_{\text{proj}}$$

---

## 5. Tabla Comparativa de Arquitecturas Seminales

| Arquitectura | Año | Capas | Parámetros | Innovación Crítica | Top-5 Error (ImageNet) |
|---|---|---|---|---|---|
| **LeNet-5** | 1998 | 7 | ~60 K | Convolución 2D, Weight Sharing, Subsampling | — (MNIST) |
| **AlexNet** | 2012 | 8 | 61 M | GPU CUDA, ReLU, Dropout, Local Response Norm | 15.3 % |
| **VGG-16** | 2014 | 16 | 138 M | Factorización homogénea de kernels $3 \times 3$ | 7.3 % |
| **ResNet-50** | 2016 | 50 | 25.5 M | Bloques Residuales Bottleneck, Skip Connections | 5.25 % |
| **ResNet-152** | 2016 | 152 | 60.2 M | Profundidad ultra-profunda sin degradación | 4.49 % |

---

## 6. Implementación Pura en Python y NumPy (Algoritmo im2col y GEMM)

En sistemas de alto rendimiento (cuDNN, OneDNN), las convoluciones no se ejecutan con bucles anidados $\mathcal{O}(H W k_h k_w)$, sino mediante el algoritmo **`im2col`**, que reordena los parches espaciales de la imagen en columnas matriciales para transformar la convolución en una multiplicación de matrices de alta velocidad (GEMM).

A continuación se implementa la convolución 2D matricial optimizada y un **Bloque Residual ResNet Completo** con conexión de identidad y backward pass en NumPy puro.

```python
import numpy as np


def im2col_indices(x, kh, kw, padding=1, stride=1):
    """
    Transforma tensores 4D de imagen (N, C, H, W) en matrices 2D
    para reducir la convolución a una multiplicación matricial pura (GEMM).
    """
    N, C, H, W = x.shape
    out_h = int((H + 2 * padding - kh) / stride + 1)
    out_w = int((W + 2 * padding - kw) / stride + 1)

    x_padded = np.pad(x, ((0, 0), (0, 0), (padding, padding), (padding, padding)), mode='constant')

    # Coordenadas de índices
    i0 = np.repeat(np.arange(kh), kw)
    i0 = np.tile(i0, C)
    i1 = stride * np.repeat(np.arange(out_h), out_w)
    j0 = np.tile(np.arange(kw), kh * C)
    j1 = stride * np.tile(np.arange(out_w), out_h)

    i = i0.reshape(-1, 1) + i1.reshape(1, -1)
    j = j0.reshape(-1, 1) + j1.reshape(1, -1)
    k = np.repeat(np.arange(C), kh * kw).reshape(-1, 1)

    cols = x_padded[:, k, i, j]
    cols = cols.transpose(1, 2, 0).reshape(kh * kw * C, -1)
    return cols, out_h, out_w


def col2im_indices(cols, x_shape, kh, kw, padding=1, stride=1):
    """Operación inversa de im2col para propagar gradientes hacia la entrada."""
    N, C, H, W = x_shape
    H_padded, W_padded = H + 2 * padding, W + 2 * padding
    x_padded = np.zeros((N, C, H_padded, W_padded), dtype=cols.dtype)

    out_h = int((H + 2 * padding - kh) / stride + 1)
    out_w = int((W + 2 * padding - kw) / stride + 1)

    i0 = np.repeat(np.arange(kh), kw)
    i0 = np.tile(i0, C)
    i1 = stride * np.repeat(np.arange(out_h), out_w)
    j0 = np.tile(np.arange(kw), kh * C)
    j1 = stride * np.tile(np.arange(out_w), out_h)

    i = i0.reshape(-1, 1) + i1.reshape(1, -1)
    j = j0.reshape(-1, 1) + j1.reshape(1, -1)
    k = np.repeat(np.arange(C), kh * kw).reshape(-1, 1)

    cols_reshaped = cols.reshape(C * kh * kw, -1, N).transpose(2, 0, 1)
    np.add.at(x_padded, (slice(None), k, i, j), cols_reshaped)

    if padding > 0:
        return x_padded[:, :, padding:-padding, padding:-padding]
    return x_padded


class Conv2D_Puro:
    """Capa Convolucional 2D vectorizada mediante descomposición matricial im2col."""
    def __init__(self, in_channels, out_channels, kernel_size=3, stride=1, padding=1):
        self.in_channels = in_channels
        self.out_channels = out_channels
        self.k = kernel_size
        self.stride = stride
        self.padding = padding
        
        # Inicialización He Normal
        std = np.sqrt(2.0 / (in_channels * kernel_size * kernel_size))
        self.W = np.random.randn(out_channels, in_channels, kernel_size, kernel_size) * std
        self.b = np.zeros((out_channels, 1))

        self.x = None
        self.x_cols = None

    def forward(self, x):
        self.x = x
        self.x_cols, out_h, out_w = im2col_indices(x, self.k, self.k, self.padding, self.stride)
        W_row = self.W.reshape(self.out_channels, -1)
        
        # Convolución expresada como producto matricial GEMM
        out = np.dot(W_row, self.x_cols) + self.b
        out = out.reshape(self.out_channels, out_h, out_w, x.shape[0]).transpose(3, 0, 1, 2)
        return out

    def backward(self, dout):
        """Retropropagación exacta de gradientes respecto a filtros y entrada."""
        dout_reshaped = dout.transpose(1, 2, 3, 0).reshape(self.out_channels, -1)
        
        # Gradientes de filtros W y sesgo b
        dW = np.dot(dout_reshaped, self.x_cols.T).reshape(self.W.shape)
        db = np.sum(dout_reshaped, axis=1, keepdims=True)

        # Gradiente respecto a la entrada X
        W_row = self.W.reshape(self.out_channels, -1)
        dX_cols = np.dot(W_row.T, dout_reshaped)
        dX = col2im_indices(dX_cols, self.x.shape, self.k, self.k, self.padding, self.stride)
        return dX, dW, db


class BloqueResidual_Puro:
    """
    Bloque Residual ResNet Canónico con Conexión de Identidad: y = ReLU(F(x) + x).
    Demuestra analíticamente la autopista aditiva de gradientes.
    """
    def __init__(self, channels):
        self.channels = channels
        self.conv1 = Conv2D_Puro(channels, channels, kernel_size=3, stride=1, padding=1)
        self.conv2 = Conv2D_Puro(channels, channels, kernel_size=3, stride=1, padding=1)

        self.x_input = None
        self.out_conv1 = None
        self.out_relu1 = None
        self.out_conv2 = None
        self.out_residual = None

    def forward(self, x):
        self.x_input = x
        # 1. Primera Convolución + ReLU
        self.out_conv1 = self.conv1.forward(x)
        self.out_relu1 = np.maximum(0.0, self.out_conv1)

        # 2. Segunda Convolución
        self.out_conv2 = self.conv2.forward(self.out_relu1)

        # 3. Suma Residual con Autopista de Identidad: F(x) + x
        self.out_residual = self.out_conv2 + self.x_input

        # 4. ReLU Post-Suma
        return np.maximum(0.0, self.out_residual)

    def backward(self, dout):
        """
        Retropropagación a través del bloque residual demostrando
        el flujo aditivo: dX = dF + dout.
        """
        # Gradiente de ReLU post-suma
        dresidual = dout * (self.out_residual > 0.0).astype(np.float64)

        # Flujo 1: Rama convolucional F(x)
        dconv2, dW2, db2 = self.conv2.backward(dresidual)
        drelu1 = dconv2 * (self.out_conv1 > 0.0).astype(np.float64)
        dconv1, dW1, db1 = self.conv1.backward(drelu1)

        # Flujo 2: Autopista de Identidad (+ I * dresidual)
        dX_total = dconv1 + dresidual

        return dX_total, (dW1, db1, dW2, db2)


# =====================================================================
# Verificación Numérica: Propagación sin Atenuación de Gradientes
# =====================================================================
if __name__ == "__main__":
    np.random.seed(42)

    # Mini-lote de prueba: 2 imágenes, 4 canales, resolución 8x8
    B, C, H, W = 2, 4, 8, 8
    X = np.random.randn(B, C, H, W)

    bloque = BloqueResidual_Puro(channels=C)
    salida = bloque.forward(X)

    # Simular tensor de gradiente recibido de capas superiores
    d_salida = np.ones_like(salida)
    dX, grads = bloque.backward(d_salida)

    print("=== Validación Numérica: Bloque ResNet Puro y Autopista de Gradientes ===")
    print(f"Tensor de entrada X: shape {X.shape}")
    print(f"Tensor de salida Y:  shape {salida.shape}")
    print(f"Norma media de la salida residual: {np.mean(salida):.4f}")
    print(f"Norma media del gradiente retropropagado dX: {np.mean(dX):.4f}")
    print(f"Comprobación de flujo de gradiente no nulo (mínimo absoluto en dX): {np.min(np.abs(dX)):.4e}")
    print("Demostración: El gradiente no se extingue a cero gracias a la conexión identidad.")
```

---

## 7. Directrices de Razonamiento para los Modelos de Inteligencia Artificial en Prig IDE

Cuando un modelo de lenguaje en Prig IDE oriente, evalúe o diseñe arquitecturas convolucionales y modelos de visión computacional (`torchvision.models.resnet`, `Conv2d`, `timm`), aplicará obligatoriamente las siguientes directrices técnicas:

1. **Diseño de Kernels: Preferir Siempre $3 \times 3$:**
   - Desaconsejar el uso de filtros grandes ($5 \times 5$ o $7 \times 7$) salvo en la primera capa convolucional de entrada (*Stem*).
   - Recordar que dos capas de $3 \times 3$ ofrecen exactamente el mismo campo receptivo que una de $5 \times 5$, pero con un 28% menos de parámetros computacionales y dos funciones de activación no lineal en lugar de una.

2. **Supresión Obligatoria de Capas Densas Gigantes mediante GAP:**
   - **Prohibición de Diseños Obsoletos:** Nunca recomendar aplanar tensores convolucionales grandes directamente sobre capas lineales densas masivas (e.g. `Flatten() -> Linear(25088, 4096)` estilo AlexNet/VGG).
   - Utilizar siempre **Global Average Pooling (`nn.AdaptiveAvgPool2d((1, 1))`)** antes de la capa final de clasificación, colapsando la dimensionalidad espacial y reduciendo drásticamente el sobreajuste.

3. **Inclusión Incondicional de Conexiones Residuales en Profundidades $\ge 20$:**
   - Si una arquitectura plana supera las 15 o 20 capas, advertir al usuario sobre la **paradoja de la degradación** de He et al. y transformar inmediatamente la red a bloques residuales con enlaces de identidad $y = \mathcal{F}(x) + x$.

4. **Tratamiento del Desajuste Dimensional en Enlaces de Salto (*Skip Mismatch*):**
   - Si un bloque residual incrementa el número de canales o reduce la resolución espacial mediante stride 2, prescribir una **proyección convolucional $1 \times 1$ con stride coincidente y Batch Normalization** en la rama de salto residual (`shortcut = nn.Sequential(nn.Conv2d(..., kernel_size=1, stride=stride), nn.BatchNorm2d(...))`).

5. **Regla de Batch Normalization sin Sesgo (*Bias=False*):**
   - Cuando una capa convolucional 2D es seguida inmediatamente por `BatchNorm2d`, configurar siempre `bias=False` en la convolución (`nn.Conv2d(..., bias=False)`).
   - Justificación matemática: el centrado por la media del mini-lote $\mu_B$ en BatchNorm cancela y anula por completo cualquier sesgo aditivo constante en la convolución, haciendo que el parámetro sea inútil y redundante.
