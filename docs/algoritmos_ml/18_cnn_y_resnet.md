# Ficha Técnica: Redes Convolucionales (CNN) y Bloques Residuales (ResNet)

## 1. Identificación y Referencias Seminales
- **LeNet-5**: Yann LeCun, Léon Bottou, Yoshua Bengio, Patrick Haffner (1998). *Gradient-Based Learning Applied to Document Recognition*. *Proceedings of the IEEE*, 86(11), 2278-2324.
- **AlexNet**: Alex Krizhevsky, Ilya Sutskever, Geoffrey E. Hinton (2012). *ImageNet Classification with Deep Convolutional Neural Networks*. *NeurIPS 25*.
- **ResNet (Deep Residual Learning)**: Kaiming He, Xiangyu Zhang, Shaoqing Ren, Jian Sun (2016). *Deep Residual Learning for Image Recognition*. *CVPR 2016*, 770-778. arXiv:1512.03385. (Ganador de Best Paper Award).

---

## 2. Formulación Matemática

### 2.1. Operación de Convolución 2D Discreta
Para un tensor de entrada $X \in \mathbb{R}^{C_{in} \times H \times W}$ y un banco de filtros $K \in \mathbb{R}^{C_{out} \times C_{in} \times k_h \times k_w}$:
$$Y(c_{out}, i, j) = b(c_{out}) + \sum_{c_{in}=1}^{C_{in}} \sum_{m=0}^{k_h-1} \sum_{n=0}^{k_w-1} X(c_{in}, i \cdot s + m - p, j \cdot s + n - p) K(c_{out}, c_{in}, m, n)$$
donde $s$ es el *stride* (paso) y $p$ es el *padding* (relleno).
- **Invariancia a la Traslación**: La compartición de pesos garantiza que un patrón visual detectado en una esquina sea reconocido idénticamente en cualquier otra posición.
- **Conectividad Local**: El campo receptivo crece jerárquicamente capa tras capa.

### 2.2. Batch Normalization
Para un mini-batch $\mathcal{B} = \{x_1, \dots, x_m\}$:
$$\mu_{\mathcal{B}} = \frac{1}{m} \sum_{i=1}^m x_i, \quad \sigma_{\mathcal{B}}^2 = \frac{1}{m} \sum_{i=1}^m (x_i - \mu_{\mathcal{B}})^2$$
$$\hat{x}_i = \frac{x_i - \mu_{\mathcal{B}}}{\sqrt{\sigma_{\mathcal{B}}^2 + \epsilon}}, \quad y_i = \gamma \hat{x}_i + \beta$$
donde $\gamma$ y $\beta$ son parámetros aprendibles que permiten a la red recuperar la representación óptima.

### 2.3. Bloque Residual con Identidad (ResNet)
En redes muy profundas (>20 capas), el gradiente se desvanece y la precisión se degrada. ResNet reformula el objetivo para aprender la función residual $\mathcal{F}(x)$:
$$\mathcal{H}(x) = \mathcal{F}(x, \{W_i\}) + x$$

Regla de la Cadena para el Gradiente de Salto Residual:
$$\frac{\partial \mathcal{E}}{\partial x} = \frac{\partial \mathcal{E}}{\partial \mathcal{H}} \frac{\partial \mathcal{H}}{\partial x} = \frac{\partial \mathcal{E}}{\partial \mathcal{H}} \left( \frac{\partial \mathcal{F}}{\partial x} + I \right)$$
El término identidad $I$ actúa como una **autopista directa para el gradiente**, garantizando que $\frac{\partial \mathcal{E}}{\partial x}$ nunca se anule aunque $\frac{\partial \mathcal{F}}{\partial x} \to 0$.

---

## 3. Descomposición Modular en Bloques

1. **Bloque 1: Stem Convolucional Inicial**
   - Convolución $7 \times 7$ con stride 2 + MaxPool $3 \times 3$ para reducir resolución inicial rápidamente.
2. **Bloque 2: Bloque Residual Básico (BasicBlock / Bottleneck)**
   - Conv2D ($3 \times 3$) $\to$ BatchNorm $\to$ ReLU $\to$ Conv2D ($3 \times 3$) $\to$ BatchNorm.
3. **Bloque 3: Conexión de Identidad (Skip Connection)**
   - Adición elemento a elemento $y = \mathcal{F}(x) + x$. Si las dimensiones cambian por stride $> 1$, se aplica una proyección $1 \times 1$.
4. **Bloque 4: Activación Post-Suma**
   - Aplicación de ReLU inmediatamente después de la adición residual.
5. **Bloque 5: Global Average Pooling (GAP) y Cabezal Clasificador**
   - Reemplaza las densas pesadas colapsando las dimensiones espaciales $H \times W \to 1 \times 1$, seguido de una única capa lineal hacia las clases.

---

## 4. Diagrama de Flujo Modular (Mermaid)

```mermaid
graph TD
    classDef input fill:#1e1e2e,stroke:#89b4fa,stroke-width:2px,color:#cdd6f4;
    classDef conv fill:#181825,stroke:#f9e2af,stroke-width:2px,color:#cdd6f4;
    classDef bn fill:#181825,stroke:#a6e3a1,stroke-width:2px,color:#cdd6f4;
    classDef skip fill:#181825,stroke:#cba6f7,stroke-width:2px,color:#cdd6f4;
    classDef out fill:#181825,stroke:#f38ba8,stroke-width:2px,color:#cdd6f4;

    X["🖼️ Imagen de Entrada x ∈ ℝ^(C, H, W)"]:::input --> C1["⚡ Conv2D (3x3, Stride 1)"]:::conv
    X -.->|Autopista de Identidad (+x)| ADD["➕ Suma Residual F(x) + x"]:::skip
    C1 --> B1["⚖️ Batch Normalization 1"]:::bn
    B1 --> R1["✨ Activación ReLU"]:::bn
    R1 --> C2["⚡ Conv2D (3x3, Stride 1)"]:::conv
    C2 --> B2["⚖️ Batch Normalization 2"]:::bn
    B2 --> ADD
    ADD --> R2["✨ Activación ReLU Post-Suma"]:::bn
    R2 --> GAP["🌐 Global Average Pooling (C, 1, 1)"]:::out
    GAP --> FC["🎯 Capa Densa Final + Softmax"]:::out
```

---

## 5. Hiperparámetros Críticos y Modos de Falla

| Hiperparámetro | Rol Matemático | Rango Típico | Modo de Falla / Efecto Extremo |
|---|---|---|---|
| `kernel_size` | Tamaño de la ventana receptiva local | $3 \times 3$ (estándar) | Dos capas $3 \times 3$ tienen el mismo campo receptivo que una de $5 \times 5$, pero con 28% menos parámetros y doble no linealidad. |
| `stride` | Paso de desplazamiento del filtro | $1$ o $2$ | Stride 2 reduce a la mitad la resolución espacial ($H/2, W/2$). |
| `padding` | Relleno perimetral de ceros | `same` ($p=1$ para $k=3$) | Previene la pérdida progresiva de bordes espaciales tras múltiples convoluciones. |

---

## 6. Snippet de Referencia en Python (PyTorch)

```python
import torch
import torch.nn as nn

class ResidualBlock(nn.Module):
    def __init__(self, channels):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(channels, channels, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(channels),
            nn.ReLU(inplace=True),
            nn.Conv2d(channels, channels, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(channels)
        )
        self.relu = nn.ReLU(inplace=True)

    def forward(self, x):
        return self.relu(self.conv(x) + x)  # Skip Connection directa
```
