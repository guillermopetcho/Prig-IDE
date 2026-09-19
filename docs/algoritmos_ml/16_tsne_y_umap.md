# Ficha Técnica: Reducción de Variedades No Lineales (t-SNE y UMAP)

## 1. Identificación y Referencias Seminales
- **t-SNE**: Laurens van der Maaten y Geoffrey Hinton (2008). *Visualizing Data using t-SNE*. *Journal of Machine Learning Research*, 9, 2579-2605.
- **UMAP**: Leland McInnes, John Healy, James Melville (2018). *UMAP: Uniform Manifold Approximation and Projection for Dimension Reduction*. arXiv:1802.03426.

---

## 2. Formulación Matemática Comparada

### 2.1. t-SNE
Convierte distancias euclidianas en afinidades probabilísticas:
- **Espacio Original (Gaussiano)**:
  $$p_{j|i} = \frac{\exp(-\|x_i - x_j\|^2 / 2\sigma_i^2)}{\sum_{k \ne i} \exp(-\|x_i - x_k\|^2 / 2\sigma_i^2)}, \quad p_{ij} = \frac{p_{j|i} + p_{i|j}}{2N}$$
  La varianza $\sigma_i$ se determina mediante búsqueda binaria para igualar la entropía de Shannon a la *Perplejidad* deseada: $\text{Perp}(P_i) = 2^{H(P_i)}$.

- **Espacio Reducido (Distribución t de Student, 1 grado de libertad)**:
  $$q_{ij} = \frac{(1 + \|y_i - y_j\|^2)^{-1}}{\sum_{k \ne l} (1 + \|y_k - y_l\|^2)^{-1}}$$
  La cola pesada de la distribución de Cauchy resuelve el *problema del hacinamiento* (*crowding problem*), repeliendo puntos moderadamente lejanos.

- **Función de Pérdida (Divergencia de Kullback-Leibler)**:
  $$\mathcal{L}_{KL} = \sum_{i \ne j} p_{ij} \log \frac{p_{ij}}{q_{ij}}$$

### 2.2. UMAP (Aproximación de Variedades Riemanniana Difusa)
Asume que los datos descansan sobre una variedad Riemanniana localmente conexa con una métrica localmente constante:
- **Grafo Difuso de Entrada**:
  $$p_{i|j} = \exp\left( -\frac{\max(0, d(x_i, x_j) - \rho_i)}{\sigma_i} \right), \quad p_{ij} = p_{i|j} + p_{j|i} - p_{i|j} p_{j|i}$$
  donde $\rho_i$ es la distancia al vecino más cercano de $x_i$ (garantizando conectividad local).
- **Afinidad en Espacio de Baja Dimensión**:
  $$q_{ij} = \left( 1 + a \|y_i - y_j\|^{2b} \right)^{-1}$$
- **Pérdida (Entropía Cruzada Difusa)**:
  $$\mathcal{L}_{UMAP} = \sum_{i \ne j} \left[ p_{ij} \log \frac{p_{ij}}{q_{ij}} + (1 - p_{ij}) \log \frac{1 - p_{ij}}{1 - q_{ij}} \right]$$
  A diferencia de KL en t-SNE, el segundo término preserva simultáneamente la **topología global** de los datos.

---

## 3. Descomposición Modular en Bloques

1. **Bloque 1: Estimador de Vecindarios de Alta Dimensión**
   - t-SNE: Barnes-Hut Tree o FFT (FIt-SNE).
   - UMAP: Nearest-Neighbor Descent (NN-Descent) de complejidad $\mathcal{O}(N^{1.14})$.
2. **Bloque 2: Calibrador de Afinidades / Grafo Simplicial**
   - t-SNE: Búsqueda de $\sigma_i$ por perplejidad.
   - UMAP: Construcción de grafo ponderado de conectividad difusa.
3. **Bloque 3: Inicializador de Coordenadas Latentes**
   - UMAP utiliza Laplaciano de Grafo / Spectral Embedding (evita desorden inicial).
   - t-SNE suele inicializarse aleatoriamente o con los 2 primeros componentes de PCA.
4. **Bloque 4: Optimizador de Fuerzas Atractivas y Repulsivas**
   - Gradiente de atracción para pares con $p_{ij} > 0$ y repulsión para puntos disimilares.
   - UMAP utiliza muestreo estocástico negativo (Negative Sampling), permitiendo escalar a millones de muestras.

---

## 4. Diagrama de Flujo Modular (Mermaid)

```mermaid
graph TD
    classDef input fill:#1e1e2e,stroke:#89b4fa,stroke-width:2px,color:#cdd6f4;
    classDef graph fill:#181825,stroke:#f9e2af,stroke-width:2px,color:#cdd6f4;
    classDef opt fill:#181825,stroke:#a6e3a1,stroke-width:2px,color:#cdd6f4;
    classDef out fill:#181825,stroke:#cba6f7,stroke-width:2px,color:#cdd6f4;

    A["📊 Dataset X (N muestras, D variables)"]:::input --> B{"Algoritmo Seleccionado"}:::graph
    B -->|t-SNE| C["🔍 Búsqueda Binaria de σ_i por Perplejidad"]:::graph
    B -->|UMAP| D["🌐 NN-Descent + Grafo Simplicial Difuso con radio local ρ_i"]:::graph
    C --> E["⚖️ Afinidad Gaussiana P_ij + Cauchy Q_ij (Colas Pesadas)"]:::opt
    D --> F["⚡ Inicialización Espectral (Laplaciano del Grafo)"]:::opt
    E --> G["🔄 Minimización de Divergencia KL con Early Exaggeration"]:::opt
    F --> H["🔄 Descenso por Entropía Cruzada Difusa con Muestreo Negativo"]:::opt
    G --> I["🚀 Proyección 2D/3D (Estructura Local Preservada)"]:::out
    H --> J["🚀 Proyección 2D/3D (Estructura Local Y Global Preservada)"]:::out
```

---

## 5. Hiperparámetros Críticos y Modos de Falla

| Algoritmo | Hiperparámetro | Rango Típico | Efecto |
|---|---|---|---|
| **t-SNE** | `perplexity` | $[5, 50]$ | Número efectivo de vecinos; valores bajos forman micro-clústeres fragmentados. |
| **t-SNE** | `early_exaggeration` | $[12.0, 24.0]$ | Fuerza clusters apretados al inicio; influye en la separación visual. |
| **UMAP** | `n_neighbors` | $[5, 100]$ | Balance local vs global: bajo $\implies$ detalles locales; alto $\implies$ macro-estructura. |
| **UMAP** | `min_dist` | $[0.01, 0.5]$ | Distancia mínima entre puntos proyectados; valores bajos empaquetan los clústeres densamente. |

---

## 6. Snippet de Referencia en Python

```python
from sklearn.manifold import TSNE
import umap

# t-SNE
tsne = TSNE(n_components=2, perplexity=30, learning_rate='auto', init='pca', random_state=42)
X_tsne = tsne.fit_transform(X)

# UMAP
reducer = umap.UMAP(n_neighbors=15, min_dist=0.1, n_components=2, random_state=42)
X_umap = reducer.fit_transform(X)
```

