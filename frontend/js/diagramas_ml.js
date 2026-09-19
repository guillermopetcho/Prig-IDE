/**
 * Graficador Modular de Flujo para Machine Learning y Deep Learning
 * Prig IDE - Sección de Aprendizaje (Diagramas)
 */
class DiagramasMLManager {
    constructor() {
        this.arquetipoActual = 'pipeline_ml';
        this.diagramaPersonalizado = null; // Para diagramas cargados desde Kaggle
        this.tituloPersonalizado = '';
        this.modulosPersonalizados = {
            entrada: 'tabular',
            preproceso: 'standard_scaler',
            modelo: 'xgboost',
            perdida: 'cross_entropy',
            optimizador: 'adam',
            metricas: 'accuracy_f1'
        };
        this.nodoSeleccionado = null;
        this.init();
    }

    init() {
        this.bindEvents();
    }

    bindEvents() {
        const btnArquetipos = document.querySelectorAll('.btn-arquetipo-ml');
        btnArquetipos.forEach(btn => {
            btn.onclick = () => {
                btnArquetipos.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                this.arquetipoActual = btn.dataset.arquetipo;
                this.diagramaPersonalizado = null;
                this.render();
            };
        });

        // Controles modulares
        ['entrada', 'preproceso', 'modelo', 'perdida', 'optimizador', 'metricas'].forEach(tipo => {
            const el = document.getElementById(`sel-mod-${tipo}`);
            if (el) {
                el.onchange = () => {
                    this.modulosPersonalizados[tipo] = el.value;
                    if (this.arquetipoActual === 'modular') {
                        this.render();
                    }
                };
            }
        });

        const btnCopiar = document.getElementById('btn-copiar-diagrama-ml');
        if (btnCopiar) btnCopiar.onclick = () => this.copiarMermaid();

        const btnInsertar = document.getElementById('btn-insertar-codigo-diagrama');
        if (btnInsertar) btnInsertar.onclick = () => this.insertarCodigoEnEditor();

        const btnChat = document.getElementById('btn-consultar-diagrama-chat');
        if (btnChat) btnChat.onclick = () => this.consultarConTutor();
    }

    abrir() {
        const modal = document.getElementById('modal-seguimiento');
        if (modal) {
            modal.style.display = 'flex';
            if (window.cambiarPestanaAprendizaje) {
                window.cambiarPestanaAprendizaje('diagramas');
            }
        }
        this.render();
    }

    cargarDiagramaExterno(mermaidCode, titulo) {
        this.diagramaPersonalizado = mermaidCode;
        this.tituloPersonalizado = titulo || 'Diagrama de Algoritmo de Kaggle';
        this.arquetipoActual = 'externo';

        const btnArquetipos = document.querySelectorAll('.btn-arquetipo-ml');
        btnArquetipos.forEach(b => b.classList.remove('active'));

        this.abrir();
    }

    obtenerMermaidCode() {
        if (this.diagramaPersonalizado && this.arquetipoActual === 'externo') {
            return this.diagramaPersonalizado;
        }

        switch (this.arquetipoActual) {
            case 'pipeline_ml':
                return `
graph TD
    classDef data fill:#1e1e2e,stroke:#89b4fa,stroke-width:2px,color:#cdd6f4;
    classDef prep fill:#181825,stroke:#f9e2af,stroke-width:2px,color:#cdd6f4;
    classDef model fill:#181825,stroke:#a6e3a1,stroke-width:2px,color:#cdd6f4;
    classDef eval fill:#181825,stroke:#cba6f7,stroke-width:2px,color:#cdd6f4;
    classDef out fill:#181825,stroke:#f38ba8,stroke-width:2px,color:#cdd6f4;

    A["📊 Ingesta de Datos (CSV / DataFrames)"]:::data --> B["🧹 Limpieza e Imputación de Nulos"]:::prep
    B --> C["⚖️ Feature Scaling (StandardScaler / Normalizer)"]:::prep
    C --> D["✂️ Train / Test Split (80% / 20%)"]:::prep
    D --> E["🌲 Estimador Predictivo (XGBoost / LightGBM / RF)"]:::model
    E --> F["🎯 Función de Pérdida / Coste (Log-Loss / MSE)"]:::eval
    E --> G["📈 Evaluación de Métricas (Accuracy, F1-Score, ROC-AUC)"]:::eval
    G --> H["🚀 Inferencia y Predicciones en Producción"]:::out
`;
            case 'xgboost':
                return `
graph TD
    classDef data fill:#1e1e2e,stroke:#89b4fa,stroke-width:2px,color:#cdd6f4;
    classDef taylor fill:#181825,stroke:#f9e2af,stroke-width:2px,color:#cdd6f4;
    classDef split fill:#181825,stroke:#a6e3a1,stroke-width:2px,color:#cdd6f4;
    classDef leaf fill:#181825,stroke:#cba6f7,stroke-width:2px,color:#cdd6f4;
    classDef ens fill:#181825,stroke:#f38ba8,stroke-width:2px,color:#cdd6f4;

    A["📊 Instancias X, y en Iteración t"]:::data --> B["📐 Gradientes g_i y Hessianos h_i (Taylor 2º Orden)"]:::taylor
    B --> C["📦 Weighted Quantile Sketch (Bins de División)"]:::taylor
    C --> D["🔍 Evaluación de Ganancia de Split: Gain(L, R)"]:::split
    D --> E{"¿Gain > γ?"}:::split
    E -->|Sí| F["🌿 División Izq/Der + Ruta Default para Nulos"]:::split
    E -->|No| G["✂️ Podar División (Nodo Terminal)"]:::leaf
    F --> H["🍃 Pesos Óptimos de Hoja: w* = -G / (H + λ)"]:::leaf
    G --> H
    H --> I["➕ Actualización con Shrinkage: ŷ ← ŷ + η·w*"]:::ens
`;
            case 'lightgbm':
                return `
graph TD
    classDef data fill:#1e1e2e,stroke:#89b4fa,stroke-width:2px,color:#cdd6f4;
    classDef efb fill:#181825,stroke:#f9e2af,stroke-width:2px,color:#cdd6f4;
    classDef goss fill:#181825,stroke:#a6e3a1,stroke-width:2px,color:#cdd6f4;
    classDef leaf fill:#181825,stroke:#cba6f7,stroke-width:2px,color:#cdd6f4;
    classDef out fill:#181825,stroke:#f38ba8,stroke-width:2px,color:#cdd6f4;

    A["📊 Datos Tabulares (Alta Dimensionalidad)"]:::data --> B["🎨 EFB: Agrupación de Variables Exclusivas (Bundling)"]:::efb
    B --> C["📦 Bins Discretos de Histogramas (uint8, 256 cubetas)"]:::efb
    C --> D["⚡ GOSS: Top a% Gradientes Altos + Submuestra b% Bajos"]:::goss
    D --> E["🌱 Expansión Leaf-Wise: Dividir la Hoja con MAYOR Ganancia"]:::leaf
    E --> F["⚡ Sustracción de Histogramas: Hist_R = Hist_Padre - Hist_L"]:::leaf
    F --> G["🚀 Inferencia Ultrarrápida 20x"]:::out
`;
            case 'catboost':
                return `
graph TD
    classDef data fill:#1e1e2e,stroke:#89b4fa,stroke-width:2px,color:#cdd6f4;
    classDef perm fill:#181825,stroke:#f9e2af,stroke-width:2px,color:#cdd6f4;
    classDef cat fill:#181825,stroke:#a6e3a1,stroke-width:2px,color:#cdd6f4;
    classDef tree fill:#181825,stroke:#cba6f7,stroke-width:2px,color:#cdd6f4;
    classDef out fill:#181825,stroke:#f38ba8,stroke-width:2px,color:#cdd6f4;

    A["📊 Dataset con Variables Categóricas y Numéricas"]:::data --> B["🔀 Generador de Permutaciones Aleatorias Múltiples σ"]:::perm
    B --> C["🎯 Ordered Target Statistics (Sin Target Leakage)"]:::cat
    C --> D["🔗 Cruces Automáticos de Variables Categóricas"]:::cat
    D --> E["📐 Ordered Boosting: Pseudo-residuos Insesgados"]:::perm
    E --> F["🌲 Árboles Oblivious Simétricos (Criterio Idéntico por Nivel)"]:::tree
    F --> G["⚡ Inferencia por Indexación Binaria Bitwise O(d)"]:::out
`;
            case 'random_forest':
                return `
graph TD
    classDef data fill:#1e1e2e,stroke:#89b4fa,stroke-width:2px,color:#cdd6f4;
    classDef boot fill:#181825,stroke:#f9e2af,stroke-width:2px,color:#cdd6f4;
    classDef tree fill:#181825,stroke:#a6e3a1,stroke-width:2px,color:#cdd6f4;
    classDef agg fill:#181825,stroke:#cba6f7,stroke-width:2px,color:#cdd6f4;

    A["📊 Dataset de Entrada D (N muestras, D variables)"]:::data --> B1["🔄 Bootstrap Sample 1 (~63.2%)"]:::boot
    A --> B2["🔄 Bootstrap Sample 2 (~63.2%)"]:::boot
    A --> B3["🔄 Bootstrap Sample B (~63.2%)"]:::boot

    B1 --> T1["🌲 Árbol 1: Split con m = √D features aleatorios"]:::tree
    B2 --> T2["🌲 Árbol 2: Split con m = √D features aleatorios"]:::tree
    B3 --> TB["🌲 Árbol B: Split con m = √D features aleatorios"]:::tree

    T1 --> E["🗳️ Agregador de Ensamble"]:::agg
    T2 --> E
    TB --> E

    E -->|Clasificación| O1["🏆 Voto Mayoritario / Promedio Softmax"]:::agg
    E -->|Regresión| O2["📈 Promedio Aritmético de Predicciones"]:::agg
`;
            case 'svm':
                return `
graph TD
    classDef data fill:#1e1e2e,stroke:#89b4fa,stroke-width:2px,color:#cdd6f4;
    classDef kernel fill:#181825,stroke:#f9e2af,stroke-width:2px,color:#cdd6f4;
    classDef opt fill:#181825,stroke:#a6e3a1,stroke-width:2px,color:#cdd6f4;
    classDef out fill:#181825,stroke:#cba6f7,stroke-width:2px,color:#cdd6f4;

    A["📊 Muestras X e y ∈ {-1, +1} (Estandarizadas)"]:::data --> B["🌐 Evaluación de Kernel: K(x, z) = exp(-γ||x-z||²)"]:::kernel
    B --> C["⚖️ Algoritmo SMO: Optimización Dual de Multiplicadores α_i ∈ [0, C]"]:::opt
    C --> D["🎯 Detección de Vectores de Soporte (Muestras Críticas con α_i > 0)"]:::opt
    D --> E["📐 Cálculo del Sesgo b y Margen Óptimo 2/||w||"]:::opt
    E --> F["🚀 Función de Decisión: ŷ = sign(∑ α_i y_i K(x_i, x) + b)"]:::out
`;
            case 'kmeans':
                return `
graph TD
    classDef init fill:#1e1e2e,stroke:#89b4fa,stroke-width:2px,color:#cdd6f4;
    classDef loop fill:#181825,stroke:#f9e2af,stroke-width:2px,color:#cdd6f4;
    classDef check fill:#181825,stroke:#a6e3a1,stroke-width:2px,color:#cdd6f4;
    classDef out fill:#181825,stroke:#cba6f7,stroke-width:2px,color:#cdd6f4;

    A["📊 Dataset X (N muestras)"]:::init --> B["🎯 k-Means++: Elegir k centroides dispersos con prob ∝ D(x)²"]:::init
    B --> C["📍 Centroides Iniciales μ₁, ..., μ_k"]:::init
    C --> D["Paso E: Asignar cada punto x_i al centroide más próximo"]:::loop
    D --> E["Paso M: Recalcular centroides como la media baricéntrica del grupo"]:::loop
    E --> F{"¿||Δμ|| < tolerancia o iter = max_iter?"}:::check
    F -->|No| D
    F -->|Sí| G["🏁 Convergencia: Centroides Óptimos e Inercia Mínima"]:::out
`;
            case 'pca':
                return `
graph TD
    classDef data fill:#1e1e2e,stroke:#89b4fa,stroke-width:2px,color:#cdd6f4;
    classDef svd fill:#181825,stroke:#f9e2af,stroke-width:2px,color:#cdd6f4;
    classDef comp fill:#181825,stroke:#a6e3a1,stroke-width:2px,color:#cdd6f4;
    classDef out fill:#181825,stroke:#cba6f7,stroke-width:2px,color:#cdd6f4;

    A["📊 Matriz de Entrada X (N muestras, D variables)"]:::data --> B["⚖️ Centrado Estricto en Media Cero: X_c = X - media(X)"]:::data
    B --> C["📐 Descomposición en Valores Singulares: X_c = U S Vᵀ"]:::svd
    C --> D["📈 Autovalores λ_j y Ratio de Varianza Explicada Acumulada"]:::comp
    D --> E["🏆 Seleccionar k componentes principales (Varianza > 95%)"]:::comp
    E --> F["🚀 Proyección Ortogonal en Subespacio Latente: Z = X_c · V_k"]:::out
`;
            case 'mlp_dl':
                return `
graph TD
    classDef tensor fill:#1e1e2e,stroke:#89b4fa,stroke-width:2px,color:#cdd6f4;
    classDef dense fill:#181825,stroke:#a6e3a1,stroke-width:2px,color:#cdd6f4;
    classDef act fill:#181825,stroke:#f9e2af,stroke-width:2px,color:#cdd6f4;
    classDef loss fill:#181825,stroke:#f38ba8,stroke-width:2px,color:#cdd6f4;
    classDef back fill:#181825,stroke:#cba6f7,stroke-width:2px,color:#cdd6f4;

    X["🔢 Tensor de Entrada X (Batch Size, Features)"]:::tensor --> L1["⚡ Capa Densa 1 (Z₁ = W₁X + b₁)"]:::dense
    L1 --> A1["✨ Activación ReLU (A₁ = max(0, Z₁))"]:::act
    A1 --> L2["⚡ Capa Oculta 2 (Z₂ = W₂A₁ + b₂)"]:::dense
    L2 --> A2["✨ Activación ReLU (A₂ = max(0, Z₂))"]:::act
    A2 --> L3["🎯 Capa de Salida (Z₃ = W₃A₂ + b₃)"]:::dense
    L3 --> P["🔮 Softmax / Sigmoide (ŷ = probabilidades)"]:::act
    P --> J["📉 Pérdida Cross-Entropy Loss L(y, ŷ)"]:::loss
    J -.-> B1["🔄 Backpropagation (∂L/∂W por Regla de la Cadena)"]:::back
    B1 -.-> OPT["⚙️ Optimizador AdamW (W = W - η·∇W - η·λ·W)"]:::back
    OPT -.-> L1
`;
            case 'resnet':
                return `
graph TD
    classDef input fill:#1e1e2e,stroke:#89b4fa,stroke-width:2px,color:#cdd6f4;
    classDef conv fill:#181825,stroke:#f9e2af,stroke-width:2px,color:#cdd6f4;
    classDef bn fill:#181825,stroke:#a6e3a1,stroke-width:2px,color:#cdd6f4;
    classDef skip fill:#181825,stroke:#cba6f7,stroke-width:2px,color:#cdd6f4;
    classDef out fill:#181825,stroke:#f38ba8,stroke-width:2px,color:#cdd6f4;

    X["🖼️ Imagen de Entrada x ∈ ℝ^(C, H, W)"]:::input --> STEM["🔍 Stem Conv 7x7 (Stride 2) + MaxPool 3x3"]:::conv
    STEM --> C1["⚡ Conv2D 3x3 (Filtros Residuales)"]:::conv
    STEM -.->|Skip Connection Identidad (+x)| ADD["➕ Suma Residual: F(x) + x"]:::skip
    C1 --> B1["⚖️ Batch Normalization 1"]:::bn
    B1 --> R1["✨ Activación ReLU"]:::bn
    R1 --> C2["⚡ Conv2D 3x3"]:::conv
    C2 --> B2["⚖️ Batch Normalization 2"]:::bn
    B2 --> ADD
    ADD --> R2["✨ Activación ReLU Post-Suma"]:::bn
    R2 --> GAP["🌐 Global Average Pooling (GAP)"]:::out
    GAP --> FC["🎯 Capa Lineal Clasificadora + Softmax"]:::out
`;
            case 'transformer_nlp':
                return `
graph TD
    classDef tok fill:#1e1e2e,stroke:#89b4fa,stroke-width:2px,color:#cdd6f4;
    classDef attn fill:#181825,stroke:#f9e2af,stroke-width:2px,color:#cdd6f4;
    classDef ffn fill:#181825,stroke:#a6e3a1,stroke-width:2px,color:#cdd6f4;
    classDef norm fill:#181825,stroke:#cba6f7,stroke-width:2px,color:#cdd6f4;
    classDef out fill:#181825,stroke:#f38ba8,stroke-width:2px,color:#cdd6f4;

    T["📝 Tokens de Texto de Entrada"]:::tok --> EMB["🔤 Token Embeddings + Positional Encoding (RoPE)"]:::tok
    EMB --> N1["⚖️ Pre-RMSNorm / LayerNorm"]:::norm
    EMB -.->|Skip Connection 1| RES1["➕ Residual Addition"]:::norm
    N1 --> MHA["👁️ Multi-Head Self-Attention: softmax(QKᵀ / √d_k) · V"]:::attn
    MHA --> RES1
    RES1 --> N2["⚖️ Pre-RMSNorm / LayerNorm"]:::norm
    RES1 -.->|Skip Connection 2| RES2["➕ Residual Addition"]:::norm
    N2 --> FFN["⚡ Feed-Forward Network (SwiGLU / MLP 4x dim)"]:::ffn
    FFN --> RES2
    RES2 --> PROJ["🎯 Linear Head Projection (Vocabulario)"]:::out
    PROJ --> SM["📊 Probabilidades de Tokens (Softmax)"]:::out
`;
            case 'diffusion':
                return `
graph TD
    classDef clean fill:#1e1e2e,stroke:#89b4fa,stroke-width:2px,color:#cdd6f4;
    classDef noise fill:#181825,stroke:#f9e2af,stroke-width:2px,color:#cdd6f4;
    classDef unet fill:#181825,stroke:#a6e3a1,stroke-width:2px,color:#cdd6f4;
    classDef loss fill:#181825,stroke:#f38ba8,stroke-width:2px,color:#cdd6f4;

    subgraph "Entrenamiento: Predicción de Ruido"
        X0["🖼️ Imagen Limpia x_0"]:::clean --> FWD["➕ Forward Jump: x_t = √(ᾱ_t) x_0 + √(1-ᾱ_t) ε"]:::noise
        EPS["🎲 Ruido Real ε ~ N(0, I)"]:::noise --> FWD
        TIME["⏱️ Paso Temporal t"]:::noise --> EMB["Embedding Temporal de t"]:::noise
        FWD --> UNET["🧠 U-Net con Autoatención Cruzada"]:::unet
        EMB --> UNET
        UNET --> PRED["🎯 Ruido Predicho ε_θ(x_t, t)"]:::unet
        EPS --> MSE["📐 Pérdida MSE: ||ε - ε_θ(x_t, t)||²"]:::loss
        PRED --> MSE
    end

    subgraph "Inferencia: Muestreo Reverso Iterativo"
        XT["🌫️ Ruido Puro x_T ~ N(0, I)"]:::noise --> REV["🔄 Bucle Reverso T → 1 (Resta de Ruido Predicho)"]:::unet
        REV --> GEN["✨ Imagen Fotorrealista Nueva x_0"]:::clean
    end
`;
            case 'bucle_entrenamiento':
                return `
graph TD
    classDef loop fill:#1e1e2e,stroke:#89b4fa,stroke-width:2px,color:#cdd6f4;
    classDef step fill:#181825,stroke:#a6e3a1,stroke-width:2px,color:#cdd6f4;
    classDef loss fill:#181825,stroke:#f38ba8,stroke-width:2px,color:#cdd6f4;
    classDef opt fill:#181825,stroke:#f9e2af,stroke-width:2px,color:#cdd6f4;
    classDef val fill:#181825,stroke:#cba6f7,stroke-width:2px,color:#cdd6f4;

    EP["🔁 Bucle de Épocas (for epoch in range(num_epochs))"]:::loop --> BATCH["📦 DataLoader Mini-batches (inputs, targets)"]:::loop
    BATCH --> ZERO["🧹 optimizer.zero_grad() (Limpieza de Gradientes)"]:::step
    ZERO --> FWD["⏩ Forward Pass: outputs = model(inputs)"]:::step
    FWD --> LOSS["📉 Pérdida: loss = criterion(outputs, targets)"]:::loss
    LOSS --> BACK["⏪ Backward Pass: loss.backward() (Autograd)"]:::loss
    BACK --> STEP["⚙️ Actualización de Pesos: optimizer.step()"]:::opt
    STEP --> SCHED["⏱️ Learning Rate Scheduler (lr_scheduler.step())"]:::opt
    SCHED --> VAL["🧪 Evaluación en Validación (model.eval(), torch.no_grad())"]:::val
`;
            case 'modular':
            default:
                const m = this.modulosPersonalizados;
                const entLabels = { tabular: '📊 Datos Tabulares CSV', imagen: '🖼️ Imágenes RGB', texto: '📝 Texto Tokenizado', tensores: '🔢 Tensores Numéricos' };
                const prepLabels = { standard_scaler: '⚖️ StandardScaler', imputer: '🧹 Imputación Simple', tokenizacion: '🔤 Tokenizador BPE', augment: '🎨 Data Augmentation' };
                const modLabels = {
                    xgboost: '⚡ XGBoost Classifier',
                    lightgbm: '⚡ LightGBM Classifier',
                    catboost: '⚡ CatBoost Classifier',
                    random_forest: '🌲 Random Forest Ensemble',
                    svm: '🌐 SVM (Kernel RBF)',
                    kmeans: '📍 k-Means Clustering',
                    pca: '📐 PCA Reducción',
                    mlp: '🧠 Perceptrón Multicapa (MLP)',
                    resnet: '🔍 CNN / ResNet',
                    transformer: '👁️ Transformer Encoder',
                    diffusion: '✨ Difusión DDPM'
                };
                const lossLabels = { cross_entropy: '📉 Cross-Entropy Loss', mse: '📉 Mean Squared Error (MSE)', bce: '📉 Binary Cross-Entropy', focal: '📉 Focal Loss' };
                const optLabels = { adam: '⚙️ Optimizador Adam', adamw: '⚙️ Optimizador AdamW con Decaimiento', sgd: '⚙️ SGD con Momentum', rmsprop: '⚙️ RMSprop' };
                const metLabels = { accuracy_f1: '📈 Accuracy & Macro F1', roc_auc: '📈 ROC-AUC Curve', r2_rmse: '📈 R² & RMSE', confusion: '📊 Matriz de Confusión' };

                return `
graph TD
    classDef mData fill:#1e1e2e,stroke:#89b4fa,stroke-width:2px,color:#cdd6f4;
    classDef mPrep fill:#181825,stroke:#f9e2af,stroke-width:2px,color:#cdd6f4;
    classDef mMod fill:#181825,stroke:#a6e3a1,stroke-width:2px,color:#cdd6f4;
    classDef mLoss fill:#181825,stroke:#f38ba8,stroke-width:2px,color:#cdd6f4;
    classDef mOpt fill:#181825,stroke:#cba6f7,stroke-width:2px,color:#cdd6f4;
    classDef mMet fill:#181825,stroke:#89b4fa,stroke-width:2px,color:#cdd6f4;

    IN["${entLabels[m.entrada] || 'Entrada de Datos'}"]:::mData --> PR["${prepLabels[m.preproceso] || 'Preprocesamiento'}"]:::mPrep
    PR --> MD["${modLabels[m.modelo] || 'Modelo de ML/DL'}"]:::mMod
    MD --> LS["${lossLabels[m.perdida] || 'Cálculo de Pérdida'}"]:::mLoss
    LS -.-> OP["${optLabels[m.optimizador] || 'Optimizador'}"]:::mOpt
    OP -.-> MD
    MD --> MT["${metLabels[m.metricas] || 'Métricas de Evaluación'}"]:::mMet
`;
        }
    }

    render() {
        const container = document.getElementById('diagrama-ml-canvas');
        if (!container) return;

        const modPanel = document.getElementById('panel-modulos-personalizados');
        if (modPanel) {
            modPanel.style.display = this.arquetipoActual === 'modular' ? 'flex' : 'none';
        }

        const mermaidCode = this.obtenerMermaidCode().trim();
        const renderId = `mermaid-ml-${Date.now()}`;
        container.innerHTML = `<div id="${renderId}" class="mermaid" style="width:100%; display:flex; justify-content:center;"></div>`;

        if (typeof mermaid !== 'undefined') {
            try {
                mermaid.render(`${renderId}-svg`, mermaidCode).then(({ svg }) => {
                    const el = document.getElementById(renderId);
                    if (el) {
                        el.innerHTML = svg;
                        setTimeout(() => this.attachNodeInteractions(container), 200);
                    }
                }).catch(err => {
                    console.error("Error renderizando Mermaid:", err);
                    container.innerHTML = `<pre style="color:var(--accent-red); padding:10px;">${mermaidCode}</pre>`;
                });
            } catch (e) {
                container.innerHTML = `<div class="mermaid">${mermaidCode}</div>`;
                if (mermaid.contentLoaded) mermaid.contentLoaded();
            }
        } else {
            container.innerHTML = `<pre style="color:var(--text-muted); padding:10px;">${mermaidCode}</pre>`;
        }

        this.seleccionarNodoInicial();
    }

    attachNodeInteractions(container) {
        const nodes = container.querySelectorAll('.node');
        nodes.forEach(node => {
            node.style.cursor = 'pointer';
            node.onmouseenter = () => node.style.filter = 'brightness(1.25)';
            node.onmouseleave = () => node.style.filter = 'none';
            node.onclick = () => {
                const text = (node.textContent || '').trim();
                this.inspectNode(text);
            };
        });
    }

    seleccionarNodoInicial() {
        const defaults = {
            pipeline_ml: 'Estimador Predictivo',
            xgboost: 'Ganancia de Split',
            lightgbm: 'Leaf-Wise',
            catboost: 'Ordered Target Statistics',
            random_forest: 'Árbol 1',
            svm: 'Vectores de Soporte',
            kmeans: 'Paso E',
            pca: 'SVD',
            mlp_dl: 'Capa Densa',
            resnet: 'Suma Residual',
            transformer_nlp: 'Self-Attention',
            diffusion: 'U-Net',
            bucle_entrenamiento: 'Backward Pass',
            modular: 'Modelo'
        };
        const initText = defaults[this.arquetipoActual] || 'Modelo';
        this.inspectNode(initText);
    }

    inspectNode(nodeTitle) {
        this.nodoSeleccionado = nodeTitle;
        const inspector = document.getElementById('diagrama-ml-inspector');
        if (!inspector) return;

        const info = this.obtenerDetalleNodo(nodeTitle);

        let mathHtml = '';
        if (info.formula) {
            mathHtml = `
                <div style="background: rgba(0,0,0,0.35); border: 1px solid var(--border-color); border-radius: 6px; padding: 10px; margin: 10px 0;">
                    <div style="font-size: 11px; color: var(--accent-yellow); font-weight: bold; margin-bottom: 4px;">
                        <i class="fa-solid fa-square-root-variable"></i> Fundamento Matemático
                    </div>
                    <div class="katex-render" style="font-size: 13px; color: #fff; overflow-x: auto; text-align: center;">
                        ${info.formula}
                    </div>
                </div>
            `;
        }

        let codeHtml = '';
        if (info.codigo) {
            codeHtml = `
                <div style="background: var(--bg-dark); border: 1px solid var(--border-color); border-radius: 6px; padding: 10px; margin: 10px 0;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                        <span style="font-size: 11px; color: var(--accent-green); font-weight: bold;">
                            <i class="fa-solid fa-code"></i> Implementación en Python
                        </span>
                        <button class="tool-btn" style="font-size: 10px; padding: 2px 6px;" onclick="navigator.clipboard.writeText(\`${info.codigo.replace(/`/g, '\\`').replace(/\\/g, '\\\\')}\`); alert('Código copiado');">
                            <i class="fa-solid fa-copy"></i> Copiar
                        </button>
                    </div>
                    <pre style="margin: 0; font-family: 'Fira Code', monospace; font-size: 11px; color: #a6e3a1; overflow-x: auto; white-space: pre-wrap;">${info.codigo}</pre>
                </div>
            `;
        }

        inspector.innerHTML = `
            <div style="display: flex; flex-direction: column; gap: 10px;">
                <div style="border-bottom: 1px solid var(--border-color); padding-bottom: 8px;">
                    <span style="font-size: 10px; text-transform: uppercase; color: var(--accent-blue); font-weight: bold; letter-spacing: 0.5px;">Componente del Flujo</span>
                    <h3 style="margin: 4px 0 0 0; font-size: 15px; color: #fff; display: flex; align-items: center; gap: 6px;">
                        ${info.icono ? `<i class="${info.icono}" style="color: var(--accent-purple);"></i>` : ''}
                        ${info.titulo || nodeTitle}
                    </h3>
                </div>

                <div style="font-size: 12px; line-height: 1.6; color: var(--text-main);">
                    ${info.explicacion}
                </div>

                ${mathHtml}
                ${codeHtml}

                <div style="background: rgba(137,180,250,0.1); border-left: 3px solid var(--accent-blue); padding: 8px 10px; border-radius: 0 6px 6px 0; font-size: 11px; color: var(--text-muted); line-height: 1.5;">
                    <strong style="color: var(--accent-blue);"><i class="fa-solid fa-lightbulb"></i> Consejo Didáctico:</strong> ${info.consejo}
                </div>
            </div>
        `;

        if (typeof renderMathInElement !== 'undefined') {
            try {
                renderMathInElement(inspector, {
                    delimiters: [
                        { left: "$$", right: "$$", display: true },
                        { left: "$", right: "$", display: false }
                    ]
                });
            } catch (e) {}
        }
    }

    obtenerDetalleNodo(title) {
        const t = title.toLowerCase();

        // --- XGBoost ---
        if (t.includes('xgboost') || t.includes('hessiano') || t.includes('quantile') || t.includes('split') && t.includes('gain')) {
            return {
                titulo: "XGBoost: Ganancia de División y Taylor 2º Orden",
                icono: "fa-solid fa-bolt",
                explicacion: "XGBoost aproxima la función de pérdida por expansión de Taylor de segundo orden calculando gradientes $g_i$ y hessianos $h_i$. La ganancia de cada división controla la poda con el parámetro $\\gamma$.",
                formula: "$$\\text{Gain} = \\frac{1}{2} \\left[ \\frac{G_L^2}{H_L + \\lambda} + \\frac{G_R^2}{H_R + \\lambda} - \\frac{(G_L + G_R)^2}{H_L + H_R + \\lambda} \\right] - \\gamma, \\quad w_j^* = -\\frac{G_j}{H_j + \\lambda}$$",
                codigo: "import xgboost as xgb\nmodelo = xgb.XGBClassifier(n_estimators=300, learning_rate=0.03, gamma=0.1, reg_lambda=1.5, tree_method='hist')\nmodelo.fit(X_train, y_train)",
                consejo: "El hiperparámetro gamma (γ) define la ganancia mínima obligatoria para realizar un split; aumentarlo actúa como una poda conservadora directa contra el overfitting."
            };
        }

        // --- LightGBM ---
        if (t.includes('lightgbm') || t.includes('goss') || t.includes('efb') || t.includes('leaf-wise') || t.includes('histograma')) {
            return {
                titulo: "LightGBM: GOSS, EFB y Estrategia Leaf-Wise",
                icono: "fa-solid fa-feather",
                explicacion: "LightGBM utiliza GOSS (Gradient-based One-Side Sampling) para descartar instancias de gradiente pequeño sin perder precisión, EFB para fusionar variables exclusivas y crecimiento Leaf-Wise para expandir la hoja con mayor reducción de pérdida.",
                formula: "$$\\tilde{V}_j(d) = \\frac{1}{n} \\left[ \\frac{(\\sum_{A_l} g_i + \\frac{1-a}{b} \\sum_{B_l} g_i)^2}{n_l} + \\frac{(\\sum_{A_r} g_i + \\frac{1-a}{b} \\sum_{B_r} g_i)^2}{n_r} \\right]$$",
                codigo: "import lightgbm as lgb\nmodelo = lgb.LGBMClassifier(num_leaves=31, min_data_in_leaf=20, learning_rate=0.03, n_estimators=500)\nmodelo.fit(X_train, y_train)",
                consejo: "En LightGBM, `num_leaves` es el hiperparámetro maestro para controlar la complejidad del árbol; para evitar sobreajuste debe satisfacer num_leaves <= 2^(max_depth)."
            };
        }

        // --- CatBoost ---
        if (t.includes('catboost') || t.includes('target statistic') || t.includes('oblivious') || t.includes('permutacion')) {
            return {
                titulo: "CatBoost: Ordered Boosting y Árboles Oblivious",
                icono: "fa-solid fa-cat",
                explicacion: "CatBoost erradica el target leakage (fuga de etiquetas) mediante permutaciones de datos ordenadas y codifica variables categóricas en tiempo real. Utiliza árboles simétricos (oblivious) evaluables a nivel de bits.",
                formula: "$$\\hat{x}_{\\sigma_p, k} = \\frac{\\sum_{j=1}^{p-1} \\mathbb{I}(x_{\\sigma_j, k} = x_{\\sigma_p, k}) y_{\\sigma_j} + a \\cdot P}{\\sum_{j=1}^{p-1} \\mathbb{I}(x_{\\sigma_j, k} = x_{\\sigma_p, k}) + a}$$",
                codigo: "from catboost import CatBoostClassifier\nmodelo = CatBoostClassifier(iterations=600, depth=6, cat_features=['categoria1', 'categoria2'], verbose=False)\nmodelo.fit(X_train, y_train)",
                consejo: "No necesitas transformar previamente las columnas categóricas con One-Hot Encoding: pásalas directamente como `cat_features` para que CatBoost calcule sus cruces óptimos."
            };
        }

        // --- SVM ---
        if (t.includes('svm') || t.includes('vector de soporte') || t.includes('soporte') || t.includes('margen') || t.includes('kernel')) {
            return {
                titulo: "Máquinas de Vectores de Soporte (SVM & Truco del Kernel)",
                icono: "fa-solid fa-shapes",
                explicacion: "SVM maximiza el margen geométrico $2/\\|w\\|$ entre clases. El truco del kernel permite separar datos linealmente no separables proyectándolos a un espacio de Hilbert de dimensión infinita mediante RBF.",
                formula: "$$\\max_{\\alpha} \\sum_{i=1}^N \\alpha_i - \\frac{1}{2} \\sum_{i,j} \\alpha_i \\alpha_j y_i y_j K(x_i, x_j) \\quad \\text{s.t.} \\quad 0 \\le \\alpha_i \\le C, \\quad K(x, z) = e^{-\\gamma \\|x-z\\|^2}$$",
                codigo: "from sklearn.svm import SVC\nfrom sklearn.preprocessing import StandardScaler\nfrom sklearn.pipeline import make_pipeline\n\nsvm = make_pipeline(StandardScaler(), SVC(C=10.0, kernel='rbf', gamma='scale'))\nsvm.fit(X_train, y_train)",
                consejo: "El parámetro C controla el castigo de errores: un C muy alto induce margen rígido propenso a overfitting, mientras que un C bajo tolera holguras favoreciendo un margen más ancho."
            };
        }

        // --- k-Means ---
        if (t.includes('kmeans') || t.includes('k-means') || t.includes('centroide') || t.includes('lloyd') || t.includes('inercia')) {
            return {
                titulo: "k-Means: Inicialización k-means++ y Bucle Lloyd",
                icono: "fa-solid fa-circle-nodes",
                explicacion: "Agrupamiento particional no supervisado que minimiza la suma de distancias cuadráticas intra-clúster (inercia). k-means++ garantiza matemáticamente convergencia acelerada a un óptimo de calidad O(log k).",
                formula: "$$\\min_{S} \\sum_{j=1}^k \\sum_{x \\in S_j} \\|x - \\mu_j\\|^2, \\quad \\mu_j = \\frac{1}{|S_j|} \\sum_{x \\in S_j} x$$",
                codigo: "from sklearn.cluster import KMeans\nkmeans = KMeans(n_clusters=4, init='k-means++', n_init=10, random_state=42)\netiquetas = kmeans.fit_predict(X)",
                consejo: "Usa el 'Método del Codo' (Elbow Method) trazando la inercia respecto a k para identificar el número óptimo natural de clústeres."
            };
        }

        // --- PCA ---
        if (t.includes('pca') || t.includes('svd') || t.includes('autovector') || t.includes('varianza explicada')) {
            return {
                titulo: "Análisis de Componentes Principales (PCA)",
                icono: "fa-solid fa-compress",
                explicacion: "Técnica de reducción de dimensionalidad lineal no supervisada. Diagonaliza la matriz de covarianza muestral mediante Descomposición en Valores Singulares (SVD) maximizando la varianza proyectada.",
                formula: "$$X_c = U S V^T, \\quad Z = X_c V_k \\in \\mathbb{R}^{N \\times k}, \\quad \\text{EVR}_j = \\frac{\\lambda_j}{\\sum \\lambda_i}$$",
                codigo: "from sklearn.decomposition import PCA\npca = PCA(n_components=0.95)  # Retener 95% de la varianza\nX_reducido = pca.fit_transform(X_centrado)",
                consejo: "Es estrictamente obligatorio centrar los datos en media cero antes de aplicar PCA; de lo contrario, el primer componente apuntará a la media y no a la máxima varianza."
            };
        }

        // --- ResNet ---
        if (t.includes('resnet') || t.includes('skip') || t.includes('residual') || t.includes('identidad')) {
            return {
                titulo: "Bloque Residual con Salto de Identidad (ResNet)",
                icono: "fa-solid fa-image",
                explicacion: "ResNet introduce conexiones de salto de identidad (skip connections) $F(x) + x$, permitiendo entrenar redes de más de 100 capas sin desvanecimiento del gradiente gracias a la derivada d(F(x)+x)/dx = dF/dx + I.",
                formula: "$$y = \\mathcal{F}(x, \\{W_i\\}) + x \\implies \\frac{\\partial \\mathcal{E}}{\\partial x} = \\frac{\\partial \\mathcal{E}}{\\partial y} \\left( \\frac{\\partial \\mathcal{F}}{\\partial x} + I \\right)$$",
                codigo: "import torch.nn as nn\nclass ResBlock(nn.Module):\n    def __init__(self, ch):\n        super().__init__()\n        self.conv = nn.Sequential(nn.Conv2d(ch, ch, 3, padding=1), nn.BatchNorm2d(ch), nn.ReLU(), nn.Conv2d(ch, ch, 3, padding=1), nn.BatchNorm2d(ch))\n    def forward(self, x):\n        return nn.functional.relu(self.conv(x) + x)",
                consejo: "El término identidad 'I' garantiza que siempre exista un flujo directo y sin atenuación para los gradientes hacia las capas iniciales."
            };
        }

        // --- Difusión DDPM ---
        if (t.includes('difusión') || t.includes('diffusion') || t.includes('ddpm') || t.includes('unet') || t.includes('desruid') || t.includes('reverse')) {
            return {
                titulo: "Modelos Probabilísticos de Difusión (DDPM)",
                icono: "fa-solid fa-wand-magic-sparkles",
                explicacion: "Modelos generativos basados en termodinámica. Añaden ruido gaussiano de forma directa en el proceso forward y entrenan una U-Net con autoatención para estimar el ruido ε inyectado y revertir el proceso.",
                formula: "$$x_t = \\sqrt{\\bar{\\alpha}_t} x_0 + \\sqrt{1 - \\bar{\\alpha}_t} \\epsilon, \\quad \\mathcal{L}_{simple} = \\mathbb{E}[\\|\\epsilon - \\epsilon_\\theta(x_t, t)\\|^2]$$",
                codigo: "# Predicción de ruido en U-Net\npred_noise = unet(noisy_images, timesteps)\nloss = torch.nn.functional.mse_loss(pred_noise, real_noise)",
                consejo: "El truco analítico de Ho et al. permite saltar directamente al paso t sin calcular los t-1 pasos intermedios durante el entrenamiento."
            };
        }

        // --- Transformer & Attention ---
        if (t.includes('attention') || t.includes('transformer') || t.includes('atención') || t.includes('rope')) {
            return {
                titulo: "Mecanismo de Auto-Atención Escalar (Self-Attention)",
                icono: "fa-solid fa-arrows-to-eye",
                explicacion: "Calcula matrices de correlación cruzada entre consultas (Q) y claves (K) escaladas por √d_k, proyectando sobre los valores (V). Permite capturar dependencias a cualquier distancia en O(1) pasos.",
                formula: "$$\\text{Attention}(Q, K, V) = \\text{softmax}\\left(\\frac{Q K^T}{\\sqrt{d_k}}\\right) V, \\quad \\text{MultiHead} = \\text{Concat}(\\text{head}_1, ..., \\text{head}_h) W^O$$",
                codigo: "import torch.nn.functional as F\nout = F.scaled_dot_product_attention(q, k, v, is_causal=True)",
                consejo: "El factor de escala 1/√d_k previene que el producto escalar Q·K crezca demasiado en dimensiones altas, lo que causaría gradientes casi nulos en el Softmax."
            };
        }

        // --- Ingesta y Datos ---
        if (t.includes('ingesta') || t.includes('datos') || t.includes('csv')) {
            return {
                titulo: "Fase de Ingesta y Carga de Datos",
                icono: "fa-solid fa-database",
                explicacion: "Carga de conjuntos de datos desde archivos tabulares, bases de datos o tensores crudos. Es fundamental verificar dimensiones, tipos de datos (dtypes) y valores nulos antes de cualquier transformación.",
                formula: "$$X \\in \\mathbb{R}^{N \\times D}, \\quad y \\in \\mathbb{R}^{N}$$",
                codigo: "import pandas as pd\ndf = pd.read_csv('datos.csv')\nprint(f'Muestras: {len(df)}, Columnas: {df.columns.tolist()}')",
                consejo: "Evita la fuga de datos (Data Leakage) jamás calculando estadísticas de preprocesamiento usando el conjunto de test."
            };
        }

        // --- Escalado ---
        if (t.includes('scaling') || t.includes('escalado') || t.includes('standard')) {
            return {
                titulo: "Normalización y Escalado de Características",
                icono: "fa-solid fa-scale-balanced",
                explicacion: "Estandariza las columnas para que tengan media $\\mu = 0$ y desviación estándar $\\sigma = 1$. Es crucial para algoritmos basados en distancias (SVM, KNN, Redes Neuronales y Regresión con Regularización).",
                formula: "$$z = \\frac{x - \\mu}{\\sigma}$$",
                codigo: "from sklearn.preprocessing import StandardScaler\nscaler = StandardScaler()\nX_train_scaled = scaler.fit_transform(X_train)\nX_test_scaled = scaler.transform(X_test)",
                consejo: "Los árboles de decisión y Random Forest son invariantes al escalado monótono, pero para redes neuronales y SVM el escalado es indispensable."
            };
        }

        // --- Backpropagation & Optimizadores ---
        if (t.includes('back') || t.includes('gradiente') || t.includes('adam')) {
            return {
                titulo: "Retropropagación y Optimizador Adaptativo (AdamW)",
                icono: "fa-solid fa-rotate-left",
                explicacion: "Calcula los gradientes por regla de la cadena y actualiza los parámetros usando momentos de primer y segundo orden desacoplados de la regularización de pesos.",
                formula: "$$\\theta_{t+1} = \\theta_t - \\frac{\\eta}{\\sqrt{\\hat{v}_t} + \\epsilon} \\hat{m}_t - \\eta \\lambda \\theta_t$$",
                codigo: "optimizer.zero_grad()\nloss.backward()\noptimizer.step()",
                consejo: "AdamW supera a Adam estándar al tratar el Weight Decay como verdadera penalización L2 separada de los momentos adaptativos."
            };
        }

        // --- Caso genérico ---
        return {
            titulo: title,
            icono: "fa-solid fa-cube",
            explicacion: `Módulo clave del flujo: ${title}. Procesa los datos o parámetros de entrada y los transmite a la siguiente etapa del algoritmo.`,
            formula: "$$y = f(x; \\theta)$$",
            codigo: "# Componente analizado en el flujo modular\nprint('Ejecución del bloque:', " + JSON.stringify(title) + ")",
            consejo: "Verifica las dimensiones y los contratos de tipos antes y después de este bloque."
        };
    }

    copiarMermaid() {
        const code = this.obtenerMermaidCode().trim();
        navigator.clipboard.writeText(code).then(() => {
            alert('¡Código Mermaid copiado al portapapeles!');
        }).catch(() => {
            prompt('Copia el código Mermaid:', code);
        });
    }

    insertarCodigoEnEditor() {
        const info = this.obtenerDetalleNodo(this.nodoSeleccionado || 'Modelo');
        if (!info || !info.codigo) {
            alert('Selecciona un nodo con código primero.');
            return;
        }

        if (window.editorMgr && window.editorMgr.getActivePath()) {
            const currentVal = window.editorMgr.getCode();
            const newVal = currentVal + `\n\n# --- Código generado desde Graficador Modular ML (${this.nodoSeleccionado}) ---\n` + info.codigo + '\n';
            window.editorMgr.setCode(newVal);
            alert('Código insertado en el archivo actual.');
        } else {
            prompt('Copia el código Python:', info.codigo);
        }
    }

    consultarConTutor() {
        const promptText = `Explícame en detalle cómo funciona el componente "${this.nodoSeleccionado || 'del pipeline'}" en Machine Learning / Deep Learning, sus implicaciones matemáticas y buenas prácticas en Python.`;

        if (window.app && window.app.sendAIChatMessage) {
            window.app.sendAIChatMessage(promptText);
        } else {
            const chatInput = document.getElementById('chat-input');
            if (chatInput) {
                chatInput.value = promptText;
                chatInput.focus();
            }
        }
    }
}

// Inicialización global
window.diagramasML = new DiagramasMLManager();
window.abrirDiagramaEnModular = function(mermaidCode, titulo) {
    if (window.diagramasML) {
        window.diagramasML.cargarDiagramaExterno(mermaidCode, titulo);
    }
};

document.addEventListener('DOMContentLoaded', () => {
    if (!window.diagramasML) {
        window.diagramasML = new DiagramasMLManager();
    }
});
