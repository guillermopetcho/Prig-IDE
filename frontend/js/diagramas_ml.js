/**
 * Graficador Modular de Flujo para Machine Learning y Deep Learning
 * Prig IDE - Sección de Aprendizaje (Diagramas)
 */
class DiagramasMLManager {
    constructor() {
        this.arquetipoActual = 'pipeline_ml';
        this.modulosPersonalizados = {
            entrada: 'tabular',
            preproceso: 'standard_scaler',
            modelo: 'random_forest',
            perdida: 'cross_entropy',
            optimizador: 'adam',
            metricas: 'accuracy_f1'
        };
        this.nodoSeleccionado = null;
        this.init();
    }

    init() {
        // Enlazar eventos cuando el DOM esté listo
        this.bindEvents();
    }

    bindEvents() {
        // Selectores de arquetipo
        const btnArquetipos = document.querySelectorAll('.btn-arquetipo-ml');
        btnArquetipos.forEach(btn => {
            btn.onclick = () => {
                btnArquetipos.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                this.arquetipoActual = btn.dataset.arquetipo;
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

    obtenerMermaidCode() {
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
    D --> E["🌲 Entrenamiento del Modelo (Random Forest / XGBoost)"]:::model
    E --> F["🎯 Función de Pérdida / Coste (Log-Loss / MSE)"]:::eval
    E --> G["📈 Evaluación de Métricas (Accuracy, F1-Score, ROC-AUC)"]:::eval
    G --> H["🚀 Inferencia y Predicciones en Producción"]:::out
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
    B1 -.-> OPT["⚙️ Optimizador Adam (W = W - η·∇W)"]:::back
    OPT -.-> L1
`;
            case 'cnn_vision':
                return `
graph TD
    classDef img fill:#1e1e2e,stroke:#89b4fa,stroke-width:2px,color:#cdd6f4;
    classDef conv fill:#181825,stroke:#a6e3a1,stroke-width:2px,color:#cdd6f4;
    classDef pool fill:#181825,stroke:#f9e2af,stroke-width:2px,color:#cdd6f4;
    classDef dense fill:#181825,stroke:#cba6f7,stroke-width:2px,color:#cdd6f4;
    classDef out fill:#181825,stroke:#f38ba8,stroke-width:2px,color:#cdd6f4;

    IMG["🖼️ Imagen de Entrada (B, 3, H, W)"]:::img --> C1["🔍 Conv2D (Filtros 3x3, Stride 1)"]:::conv
    C1 --> BN1["📏 Batch Normalization 2D"]:::conv
    BN1 --> ACT1["✨ Activación ReLU"]:::conv
    ACT1 --> P1["🌊 Max Pooling 2D (Submuestreo 2x2)"]:::pool
    P1 --> C2["🔍 Conv2D Profunda (Canales duplicados)"]:::conv
    C2 --> P2["🌊 Max Pooling 2D"]:::pool
    P2 --> GAP["📐 Global Average Pooling / Flatten"]:::pool
    GAP --> FC["⚡ Capa Densa Totalmente Conectada"]:::dense
    FC --> SM["🎯 Softmax (K clases)"]:::out
`;
            case 'transformer_nlp':
                return `
graph TD
    classDef tok fill:#1e1e2e,stroke:#89b4fa,stroke-width:2px,color:#cdd6f4;
    classDef attn fill:#181825,stroke:#f9e2af,stroke-width:2px,color:#cdd6f4;
    classDef ffn fill:#181825,stroke:#a6e3a1,stroke-width:2px,color:#cdd6f4;
    classDef norm fill:#181825,stroke:#cba6f7,stroke-width:2px,color:#cdd6f4;
    classDef out fill:#181825,stroke:#f38ba8,stroke-width:2px,color:#cdd6f4;

    T["📝 Tokens de Texto de Entrada"]:::tok --> EMB["🔤 Token Embeddings + Positional Encoding"]:::tok
    EMB --> MHA["👁️ Multi-Head Self-Attention (Q, K, V)"]:::attn
    MHA --> RES1["➕ Residual Connection & LayerNorm"]:::norm
    RES1 --> FFN["⚡ Feed-Forward Network (Linear -> GELU -> Linear)"]:::ffn
    FFN --> RES2["➕ Residual Connection & LayerNorm"]:::norm
    RES2 --> PROJ["🎯 Linear Head Projection (Vocabulario)"]:::out
    PROJ --> SM["📊 Probabilidades de Siguiente Token (Softmax)"]:::out
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
                const modLabels = { random_forest: '🌲 Random Forest Ensemble', xgboost: '⚡ XGBoost Classifier', mlp: '🧠 Perceptrón Multicapa (MLP)', cnn: '🔍 Red Convolucional (CNN)', transformer: '👁️ Transformer Encoder' };
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

        // Mostrar / ocultar panel modular según arquetipo
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
                        setTimeout(() => this.attachNodeInteractions(container), 250);
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

        // Si no hay nodo seleccionado, mostrar el inicial del arquetipo
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
            pipeline_ml: 'Entrenamiento del Modelo',
            mlp_dl: 'Capa Densa',
            cnn_vision: 'Conv2D',
            transformer_nlp: 'Multi-Head Self-Attention',
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
                        <button class="tool-btn" style="font-size: 10px; padding: 2px 6px;" onclick="navigator.clipboard.writeText(\`${info.codigo.replace(/`/g, '\\`')}\`); alert('Código copiado');">
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

        // Renderizar KaTeX si está disponible
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

        if (t.includes('scaling') || t.includes('escalado') || t.includes('standard')) {
            return {
                titulo: "Normalización y Escalado de Características",
                icono: "fa-solid fa-scale-balanced",
                explicacion: "Estandariza las columnas para que tengan media $\\mu = 0$ y desviación estándar $\\sigma = 1$. Es crucial para algoritmos basados en distancias (SVM, KNN, Redes Neuronales y Regresión con Regularización).",
                formula: "$$z = \\frac{x - \\mu}{\\sigma}$$",
                codigo: "from sklearn.preprocessing import StandardScaler\nscaler = StandardScaler()\nX_train_scaled = scaler.fit_transform(X_train)\nX_test_scaled = scaler.transform(X_test)  # Solo transform en test!",
                consejo: "Los árboles de decisión y Random Forest son invariantes al escalado monótono, pero para redes neuronales el escalado es obligatorio para evitar gradientes explosivos o desvanecidos."
            };
        }

        if (t.includes('split') || t.includes('train')) {
            return {
                titulo: "Partición Train / Test Split",
                icono: "fa-solid fa-scissors",
                explicacion: "Separa el conjunto de datos en entrenamiento (usualmente 70-80%) y evaluación final (20-30%). Para datos desbalanceados debe usarse estratificación (stratify=y).",
                formula: "$$\\mathcal{D}_{total} = \\mathcal{D}_{train} \\cup \\mathcal{D}_{test}, \\quad \\mathcal{D}_{train} \\cap \\mathcal{D}_{test} = \\emptyset$$",
                codigo: "from sklearn.model_selection import train_test_split\nX_train, X_test, y_train, y_test = train_test_split(\n    X, y, test_size=0.2, random_state=42, stratify=y\n)",
                consejo: "Fija siempre el parámetro 'random_state' para garantizar reproducibilidad exacta en tus experimentos."
            };
        }

        if (t.includes('random forest') || t.includes('entrenamiento') || t.includes('árbol')) {
            return {
                titulo: "Ensemble de Árboles (Random Forest)",
                icono: "fa-solid fa-tree",
                explicacion: "Conjunto de árboles de decisión entrenados mediante Bagging (Bootstrap Aggregating) con selección aleatoria de características en cada división, reduciendo la varianza sin aumentar el sesgo.",
                formula: "$$\\hat{y} = \\frac{1}{B} \\sum_{b=1}^B T_b(x) \\quad \\text{(Regresión)} \\quad \\text{o} \\quad \\text{Moda}(T_1(x), ..., T_B(x))$$",
                codigo: "from sklearn.ensemble import RandomForestClassifier\nrf = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42)\nrf.fit(X_train, y_train)\nprint(f'Accuracy en test: {rf.score(X_test, y_test):.4f}')",
                consejo: "Revisa `rf.feature_importances_` para descubrir cuáles son las variables más predictivas de tu dataset."
            };
        }

        if (t.includes('densa') || t.includes('capa') || t.includes('linear')) {
            return {
                titulo: "Capa Lineal / Densa Totalmente Conectada",
                icono: "fa-solid fa-layer-group",
                explicacion: "Aplica una transformación afín a las entradas: multiplica por la matriz de pesos $W$ y suma el vector de sesgo (bias) $b$. Cada neurona se conecta a todas las neuronas de la capa anterior.",
                formula: "$$Z = W \\cdot X + b, \\quad W \\in \\mathbb{R}^{d_{out} \\times d_{in}}$$",
                codigo: "import torch\nimport torch.nn as nn\n\n# Capa de 64 entradas a 128 neuronas de salida\nlinear = nn.Linear(in_features=64, out_features=128)\nz = linear(x)",
                consejo: "Sin una función de activación no lineal entre capas densas, múltiples capas consecutivas se colapsan matemáticamente en una sola transformación lineal."
            };
        }

        if (t.includes('relu') || t.includes('activación')) {
            return {
                titulo: "Función de Activación No Lineal (ReLU)",
                icono: "fa-solid fa-chart-line",
                explicacion: "Introduce la no-linealidad necesaria para que la red neuronal aprenda funciones complejas. ReLU (Rectified Linear Unit) es eficiente y mitiga el desvanecimiento de gradientes en valores positivos.",
                formula: "$$\\sigma(z) = \\max(0, z), \\quad \\frac{d\\sigma}{dz} = \\begin{cases} 1 & z > 0 \\\\ 0 & z < 0 \\end{cases}$$",
                codigo: "import torch.nn.functional as F\na = F.relu(z)\n# Alternativa moderna: GELU o SiLU/Swish",
                consejo: "Cuidado con el 'Dying ReLU': si una neurona recibe siempre entradas negativas con gradiente 0, deja de actualizarse de por vida. En tales casos prueba LeakyReLU o GELU."
            };
        }

        if (t.includes('loss') || t.includes('pérdida') || t.includes('cross-entropy')) {
            return {
                titulo: "Función de Pérdida (Cross-Entropy Loss)",
                icono: "fa-solid fa-arrow-trend-down",
                explicacion: "Cuantifica el error entre la distribución de probabilidad predicha $\\hat{y}$ y las etiquetas verdaderas $y$. El objetivo del entrenamiento es minimizar este valor.",
                formula: "$$\\mathcal{L}_{CE} = -\\frac{1}{N} \\sum_{i=1}^N \\sum_{c=1}^C y_{i,c} \\log(\\hat{y}_{i,c})$$",
                codigo: "import torch.nn as nn\ncriterion = nn.CrossEntropyLoss()\nloss = criterion(logits, targets)",
                consejo: "En PyTorch, `nn.CrossEntropyLoss` espera los logits crudos (sin aplicar Softmax antes) para mayor estabilidad numérica mediante la técnica log-sum-exp."
            };
        }

        if (t.includes('back') || t.includes('gradiente') || t.includes('cadena')) {
            return {
                titulo: "Retropropagación (Backpropagation) y Autograd",
                icono: "fa-solid fa-rotate-left",
                explicacion: "Calcula el gradiente de la función de coste con respecto a cada uno de los pesos de la red utilizando la Regla de la Cadena del cálculo multivariable.",
                formula: "$$\\frac{\\partial \\mathcal{L}}{\\partial W^{[l]}} = \\frac{\\partial \\mathcal{L}}{\\partial Z^{[l]}} \\cdot (A^{[l-1]})^T, \\quad \\frac{\\partial \\mathcal{L}}{\\partial Z^{[l]}} = \\frac{\\partial \\mathcal{L}}{\\partial A^{[l]}} \\odot \\sigma'(Z^{[l]})$$",
                codigo: "optimizer.zero_grad()  # 1. Limpiar gradientes anteriores\nloss.backward()         # 2. Backpropagation automático\noptimizer.step()        # 3. Actualizar pesos",
                consejo: "Si no llamas a `optimizer.zero_grad()` en cada iteración de PyTorch, los gradientes se acumulan en lugar de reemplazarse, arruinando el entrenamiento."
            };
        }

        if (t.includes('opt') || t.includes('adam') || t.includes('sgd')) {
            return {
                titulo: "Optimizador Adaptativo (Adam / AdamW)",
                icono: "fa-solid fa-gears",
                explicacion: "Combina las ventajas de Momentum (primer momento del gradiente) y RMSprop (segundo momento de los gradientes al cuadrado) para adaptar individualmente la tasa de aprendizaje de cada peso.",
                formula: "$$m_t = \\beta_1 m_{t-1} + (1-\\beta_1) g_t, \\quad v_t = \\beta_2 v_{t-1} + (1-\\beta_2) g_t^2, \\quad \\theta_{t+1} = \\theta_t - \\frac{\\eta}{\\sqrt{\\hat{v}_t} + \\epsilon} \\hat{m}_t$$",
                codigo: "import torch.optim as optim\noptimizer = optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-2)",
                consejo: "AdamW es preferido sobre Adam clásico porque desacopla el decaimiento de pesos (Weight Decay) de las actualizaciones de gradiente adaptativas."
            };
        }

        if (t.includes('conv') || t.includes('convolución')) {
            return {
                titulo: "Capa Convolucional 2D (Conv2D)",
                icono: "fa-solid fa-magnifying-glass",
                explicacion: "Desliza filtros o núcleos (kernels) espaciales a lo largo de la imagen para extraer mapas de características locales como bordes, texturas y formas complejas con invarianza traslacional.",
                formula: "$$(I * K)(i, j) = \\sum_{m} \\sum_{n} I(i-m, j-n) K(m, n)$$",
                codigo: "import torch.nn as nn\nconv = nn.Conv2d(in_channels=3, out_channels=32, kernel_size=3, padding=1)",
                consejo: "Usar padding=1 con kernel de 3x3 preserva la resolución espacial (alto y ancho) de la imagen tras la convolución."
            };
        }

        if (t.includes('attention') || t.includes('transformer') || t.includes('atención')) {
            return {
                titulo: "Mecanismo de Auto-Atención Escalar (Self-Attention)",
                icono: "fa-solid fa-arrows-to-eye",
                explicacion: "Permite a cada palabra o token atender a todos los demás tokens de la secuencia en paralelo mediante vectores Query (Q), Key (K) y Value (V), capturando dependencias de largo alcance.",
                formula: "$$\\text{Attention}(Q, K, V) = \\text{softmax}\\left(\\frac{Q K^T}{\\sqrt{d_k}}\\right) V$$",
                codigo: "import torch.nn as nn\nattn = nn.MultiheadAttention(embed_dim=512, num_heads=8, batch_first=True)\nout, weights = attn(query, key, value)",
                consejo: "El factor de escala $\\frac{1}{\\sqrt{d_k}}$ evita que el producto escalar crezca demasiado con dimensiones altas, lo que empujaría la función Softmax a regiones de gradiente minúsculo."
            };
        }

        // Caso por defecto
        return {
            titulo: title,
            icono: "fa-solid fa-cube",
            explicacion: `Módulo clave del pipeline: ${title}. Procesa los datos o parámetros y pasa el resultado al siguiente bloque del flujo.`,
            formula: "$$y = f(x; \\theta)$$",
            codigo: "# Componente modular en el flujo ML/DL\nprint('Ejecución del bloque:', " + JSON.stringify(title) + ")",
            consejo: "Asegúrate de comprobar las dimensiones y el tipo de datos a la entrada y a la salida de este módulo."
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
        const info = this.obtenerDetalleNodo(this.nodoSeleccionado || 'Modelo');
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
window.addEventListener('DOMContentLoaded', () => {
    window.diagramasML = new DiagramasMLManager();
});

