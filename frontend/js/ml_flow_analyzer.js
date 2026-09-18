class MLFlowAnalyzerManager {
    constructor() {
        this.modal = document.getElementById('modal-ml-flow');
        this.reportContainer = document.getElementById('ml-flow-report');
        this.diagramContainer = document.getElementById('ml-flow-diagram');
        this.nodeInspector = document.getElementById('ml-flow-inspector');
        this.statusText = document.getElementById('ml-flow-status-text');

        this.currentRawMarkdown = '';
        this.initEvents();
    }

    initEvents() {
        const btnClose = document.getElementById('btn-close-ml-flow-modal');
        if (btnClose) btnClose.onclick = () => this.closeModal();

        const btnAnalyze = document.getElementById('btn-run-ml-analysis');
        if (btnAnalyze) btnAnalyze.onclick = () => this.analyzeCurrentCode();

        // Pestañas del modal
        const tabs = document.querySelectorAll('.ml-tab-btn');
        tabs.forEach(tab => {
            tab.onclick = () => {
                tabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');

                const targetId = tab.dataset.target;
                document.querySelectorAll('.ml-tab-pane').forEach(pane => {
                    pane.classList.remove('active');
                });
                const targetPane = document.getElementById(targetId);
                if (targetPane) targetPane.classList.add('active');
            };
        });

        // Tecla Escape para cerrar
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.modal && this.modal.style.display === 'flex') {
                this.closeModal();
            }
        });
    }

    openModal() {
        if (!this.modal) return;
        this.modal.style.display = 'flex';
        this.analyzeCurrentCode();
    }

    closeModal() {
        if (this.modal) this.modal.style.display = 'none';
    }

    async analyzeCurrentCode() {
        const codeContext = window.editorMgr ? window.editorMgr.getAIContext() : '';
        const modelSelect = document.getElementById('model-select');
        const model = modelSelect ? modelSelect.value : 'qwen2.5-coder:7b';

        if (!codeContext || !codeContext.trim()) {
            this.statusText.innerHTML = '<span style="color:var(--accent-red);"><i class="fa-solid fa-triangle-exclamation"></i> Abre un notebook o archivo de código primero para analizar.</span>';
            return;
        }

        this.statusText.innerHTML = `<span style="color:var(--accent-blue);"><i class="fa-solid fa-spinner fa-spin"></i> Analizando pipeline ML/DL con ${model}...</span>`;
        this.reportContainer.innerHTML = '<div style="padding:20px; text-align:center; color:var(--text-muted);"><i class="fa-solid fa-brain fa-bounce" style="font-size:2rem;"></i><br><br>Generando informe dinámico y diagrama de flujo...</div>';
        this.diagramContainer.innerHTML = '';
        this.nodeInspector.innerHTML = '<div style="color:var(--text-muted); font-size:12px;">Haz clic en cualquier nodo del diagrama para inspeccionar su fórmula matemática y función en el entrenamiento.</div>';

        const prompt = "Genera un informe detallado del algoritmo de Deep Learning / Machine Learning de este código, desglosando la carga de datos, la arquitectura del modelo, el loss function, el bucle de entrenamiento (forward/backward pass) y la optimización. Incluye un diagrama Mermaid `graph TD` claro.";

        try {
            const res = await fetch('/api/ai/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    prompt: prompt,
                    model: model,
                    mode: 'ml_flow',
                    code_context: codeContext
                })
            });

            if (!res.ok) {
                this.statusText.innerHTML = '<span style="color:var(--accent-red);">Error al conectar con la IA. Verifique que Ollama esté activo.</span>';
                return;
            }

            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let accumulatedText = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                accumulatedText += decoder.decode(value, { stream: true });

                // Formatear Markdown dinámicamente
                if (typeof marked !== 'undefined') {
                    this.reportContainer.innerHTML = marked.parse(accumulatedText);
                } else {
                    this.reportContainer.innerText = accumulatedText;
                }
            }

            this.currentRawMarkdown = accumulatedText;
            this.statusText.innerHTML = '<span style="color:var(--accent-green);"><i class="fa-solid fa-circle-check"></i> Análisis de Flujo ML/DL completado con éxito.</span>';

            // Extraer y Renderizar el Diagrama Mermaid
            this.extractAndRenderMermaid(accumulatedText);

        } catch (e) {
            console.error("Error analizando flujo ML/DL:", e);
            this.statusText.innerHTML = `<span style="color:var(--accent-red);">Error en análisis: ${e.message}</span>`;
        }
    }

    extractAndRenderMermaid(markdownText) {
        const mermaidMatch = markdownText.match(/```mermaid([\s\S]*?)```/);
        if (mermaidMatch && mermaidMatch[1]) {
            const mermaidCode = mermaidMatch[1].trim();
            this.diagramContainer.innerHTML = `<div class="mermaid">${mermaidCode}</div>`;

            if (typeof mermaid !== 'undefined') {
                try {
                    mermaid.contentLoaded();
                    setTimeout(() => this.attachNodeInteractions(), 400);
                } catch (err) {
                    console.error("Error cargando Mermaid:", err);
                }
            }
        } else {
            this.diagramContainer.innerHTML = '<div style="padding:20px; color:var(--text-muted); text-align:center;">El diagrama visual se generará al finalizar el análisis o puedes ver el informe escrito en la pestaña Informe.</div>';
        }
    }

    attachNodeInteractions() {
        const nodes = this.diagramContainer.querySelectorAll('.node');
        nodes.forEach(node => {
            node.style.cursor = 'pointer';
            node.onclick = () => {
                const nodeText = node.textContent || 'Nodo ML/DL';
                this.inspectNodeDetails(nodeText.trim());
            };
        });
    }

    inspectNodeDetails(nodeName) {
        let snippet = "Detalle del componente seleccionado en el pipeline.";
        let formula = "";

        if (nodeName.toLowerCase().includes('data') || nodeName.toLowerCase().includes('datos')) {
            snippet = "<strong>Fase de Datos:</strong> Prepara tensores de entrada $X$ e inspecciona las dimensiones (Batch Size, Features).";
            formula = "$$X \\in \\mathbb{R}^{B \\times C \\times H \\times W}$$";
        } else if (nodeName.toLowerCase().includes('forward') || nodeName.toLowerCase().includes('capa')) {
            snippet = "<strong>Paso Forward:</strong> Calcula la transformación lineal y no-lineal a través de las capas del modelo.";
            formula = "$$y = \\sigma(W \\cdot x + b)$$";
        } else if (nodeName.toLowerCase().includes('loss') || nodeName.toLowerCase().includes('pérdida')) {
            snippet = "<strong>Cálculo de Pérdida:</strong> Evalúa la cuantía del error entre las predicciones $\\hat{y}$ y las etiquetas reales $y$.";
            formula = "$$J(\\theta) = -\\frac{1}{N} \\sum_{i=1}^N [y_i \\log(\\hat{y}_i) + (1-y_i) \\log(1-\\hat{y}_i)]$$";
        } else if (nodeName.toLowerCase().includes('backward') || nodeName.toLowerCase().includes('gradiente')) {
            snippet = "<strong>Backpropagation:</strong> Aplica la Regla de la Cadena para obtener la derivada parcial del error con respecto a cada peso.";
            formula = "$$\\frac{\\partial J}{\\partial W} = \\frac{\\partial J}{\\partial \\hat{y}} \\cdot \\frac{\\partial \\hat{y}}{\\partial z} \\cdot \\frac{\\partial z}{\\partial W}$$";
        } else if (nodeName.toLowerCase().includes('opt') || nodeName.toLowerCase().includes('peso')) {
            snippet = "<strong>Paso de Optimización:</strong> Actualiza los pesos $W$ en dirección contraria al gradiente del costo.";
            formula = "$$W_{nuevo} = W_{viejo} - \\eta \\cdot \\nabla_W J(W)$$";
        }

        let html = `
            <div style="background:var(--bg-dark); padding:12px; border-radius:6px; border:1px solid var(--accent-blue);">
                <div style="font-weight:bold; color:var(--accent-blue); font-size:14px; margin-bottom:6px;"><i class="fa-solid fa-circle-nodes"></i> Componente: ${nodeName}</div>
                <div style="margin-bottom:8px; font-size:13px;">${snippet}</div>
                ${formula ? `<div style="background:#11111b; padding:8px; border-radius:4px; margin-top:6px;">${formula}</div>` : ''}
            </div>
        `;

        if (typeof marked !== 'undefined') {
            this.nodeInspector.innerHTML = marked.parse(html);
        } else {
            this.nodeInspector.innerHTML = html;
        }
    }
}

// Inicializar globalmente
window.addEventListener('DOMContentLoaded', () => {
    window.mlFlowAnalyzerMgr = new MLFlowAnalyzerManager();
});
