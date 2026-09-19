# Ficha Técnica: Regresión Lineal y Regularización (OLS, Ridge, Lasso, ElasticNet)

## 1. Identificación y Referencias Seminales
- **Mínimos Cuadrados Ordinarios (OLS)**: Legendre (1805), Gauss (1809).
- **Regresión Ridge ($L_2$)**: Hoerl & Kennard (1970). *Technometrics*, 12(1), 55-67.
- **Lasso ($L_1$)**: Tibshirani (1996). *JRSS-B*, 58(1), 267-288.
- **Elastic Net**: Zou & Hastie (2005). *JRSS-B*, 67(2), 301-320.

---

## 2. Formulación Matemática y Funciones de Pérdida

### 2.1. OLS
$$\mathcal{L}_{\text{OLS}}(w, b) = \frac{1}{2N} \sum_{i=1}^N \left( y_i - (w^T x_i + b) \right)^2 = \frac{1}{2N} \|y - Xw\|_2^2$$
Solución analítica exacta (Ecuaciones Normales):
$$w^* = (X^T X)^{-1} X^T y$$

### 2.2. Ridge ($L_2$)
$$\mathcal{L}_{\text{Ridge}}(w) = \frac{1}{2N} \|y - Xw\|_2^2 + \frac{\lambda}{2} \|w\|_2^2 \implies w^* = (X^T X + \lambda I)^{-1} X^T y$$

### 2.3. Lasso ($L_1$)
$$\mathcal{L}_{\text{Lasso}}(w) = \frac{1}{2N} \|y - Xw\|_2^2 + \alpha \|w\|_1$$
Operador de Umbralización Suave (Soft-Thresholding) para el Descenso por Coordenadas:
$$w_j^* = S\left( \frac{1}{N} X_j^T (y - X_{-j} w_{-j}), \alpha \right) = \text{sign}(c_j) \max(0, |c_j| - \alpha)$$

### 2.4. Elastic Net ($L_1 + L_2$)
$$\mathcal{L}_{\text{ElasticNet}}(w) = \frac{1}{2N} \|y - Xw\|_2^2 + \alpha \rho \|w\|_1 + \frac{\alpha (1-\rho)}{2} \|w\|_2^2$$

---

## 3. Descomposición Modular en Bloques

1. **Bloque 1: Ingesta y Estandarización de Datos**
   - Entrada: Matriz $X \in \mathbb{R}^{N \times D}$, Vector $y \in \mathbb{R}^N$.
   - Contrato: Centrado en $\mu = 0$ y escala $\sigma = 1$. Crítico para regularización equitativa de todos los coeficientes.
2. **Bloque 2: Matriz de Gram y Estabilización Espectral**
   - Cálculo de $X^T X$.
   - Adición de penalización $\lambda I$ en la diagonal para garantizar condicionamiento numérico positivo definido.
3. **Bloque 3: Motor de Optimización**
   - Si es analítico: Descomposición Cholesky / SVD de $(X^TX + \lambda I)$.
   - Si es ralo ($L_1$): Descenso iterativo por coordenadas cíclico.
4. **Bloque 4: Inferencia y Coeficientes**
   - Salida continua $\hat{y} = w^T x + b$.
   - Atributo de importancia de variables dado por $|w_j|$.

---

## 4. Diagrama de Flujo Modular (Mermaid)

```mermaid
graph TD
    classDef input fill:#1e1e2e,stroke:#89b4fa,stroke-width:2px,color:#cdd6f4;
    classDef proc fill:#181825,stroke:#f9e2af,stroke-width:2px,color:#cdd6f4;
    classDef opt fill:#181825,stroke:#a6e3a1,stroke-width:2px,color:#cdd6f4;
    classDef out fill:#181825,stroke:#cba6f7,stroke-width:2px,color:#cdd6f4;

    A["📊 Matriz de Entrada X (N, D) e y (N)"]:::input --> B["⚖️ Centrado y Estandarización (StandardScaler)"]:::proc
    B --> C{"Tipo de Regularización"}:::proc
    C -->|Ninguna (OLS)| D["Inversión Normal: (XᵀX)⁻¹ Xᵀy"]:::opt
    C -->|L2 (Ridge)| E["Estabilización Diagonal: (XᵀX + λI)⁻¹"]:::opt
    C -->|L1 (Lasso)| F["Descenso por Coordenadas + Soft-Thresholding"]:::opt
    C -->|L1 + L2 (ElasticNet)| G["Optimización Proximal Convexa"]:::opt
    D --> H["Vector de Pesos Óptimos w*"]:::out
    E --> H
    F --> I["Pesos Ralos (w_j = 0 para variables no útiles)"]:::out
    G --> I
    H --> J["🚀 Inferencia: ŷ = wᵀx + b"]:::out
    I --> J
```

---

## 5. Hiperparámetros Críticos y Modos de Falla

| Hiperparámetro | Rol Matemático | Rango Típico | Modo de Falla / Efecto Extremo |
|---|---|---|---|
| `alpha` ($\lambda$) | Fuerza de la penalización | $[10^{-4}, 10^3]$ | Si es muy alto $\to$ *underfitting* severo ($w \to 0$). Si es 0 $\to$ multicolinealidad. |
| `l1_ratio` ($\rho$) | Balance entre $L_1$ y $L_2$ en ElasticNet | $[0.0, 1.0]$ | $\rho=1 \implies$ Lasso puro; $\rho=0 \implies$ Ridge puro. |
| `fit_intercept` | Inclusión del término de sesgo $b$ | Booleano | Si los datos no están centrados y `fit_intercept=False`, predicciones sesgadas. |

---

## 6. Snippet de Referencia en Python

```python
from sklearn.linear_model import ElasticNet
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline

modelo = make_pipeline(
    StandardScaler(),
    ElasticNet(alpha=0.1, l1_ratio=0.5, random_state=42)
)
modelo.fit(X_train, y_train)
predicciones = modelo.predict(X_test)
```
