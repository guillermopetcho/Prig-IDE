/**
 * Prig IDE - Studio de Flujos de Agentes Dinámicos y Recursivos (v2 / SOTA)
 * Arquitectura multi-agente inspirada en LangGraph, CrewAI y AutoGen:
 * - Grafos dirigidos con memoria compartida (AgentState)
 * - Bucles recursivos de autoevaluación y corrección (Self-Reflection Loops)
 * - Enrutamiento dinámico / Supervisores
 * - Ejecución en sandbox seguro de Python con captura de stdout/stderr
 * - Streaming en tiempo real (NDJSON) con soporte KaTeX y Markdown
 */

class AgentWorkflowManager {
    constructor() {
        this.modal = document.getElementById('modal-agent-workflow');
        this.stepsContainer = document.getElementById('wf-steps-container');
        this.resultsContainer = document.getElementById('wf-results-container');
        this.statusEl = document.getElementById('wf-execution-status');
        this.timerEl = document.getElementById('wf-timer');
        this.statsEl = document.getElementById('wf-stats');
        this.iterationTabsEl = document.getElementById('wf-iteration-tabs');
        this.initialInputEl = document.getElementById('wf-initial-input');
        this.templateSelect = document.getElementById('wf-template-select');
        this.btnRun = document.getElementById('btn-run-workflow');
        this.btnStop = document.getElementById('btn-stop-workflow');
        this.btnCopy = document.getElementById('btn-copy-wf-result');

        this.models = [];
        this.nodes = [];
        this.nodeCounter = 0;
        this.abortController = null;
        this.timerInterval = null;
        this.startTime = 0;
        this.activeNodeId = null;
        this.finalResultText = "";
        this.currentIteration = 1;
        this.activeOutputNodeEl = null;

        this.initEvents();
    }

    initEvents() {
        // Evento de apertura desde barra de herramientas / workArea
        document.addEventListener('prig:herramienta-abierta', (e) => {
            if (e.detail && e.detail.modalId === 'modal-agent-workflow') {
                this.openModal();
            }
        });

        window.abrirStudioAgentes = (preset = null) => {
            if (window.workArea) {
                window.workArea.abrirHerramienta('modal-agent-workflow', 'Studio Agentes', 'fa-diagram-project');
            } else {
                this.openModal(preset);
            }
            if (preset) this.loadTemplate(preset);
        };

        // Modal cerrar
        const btnClose = document.getElementById('btn-close-workflow-modal');
        if (btnClose) btnClose.onclick = () => this.closeModal();

        // Tecla escape
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.modal && this.modal.style.display === 'flex') {
                this.closeModal();
            }
        });

        // Selector de Plantillas SOTA
        if (this.templateSelect) {
            this.templateSelect.onchange = (e) => {
                const val = e.target.value;
                if (val) this.loadTemplate(val);
            };
        }

        // Botones de agregar nodos por tipo
        const btnAddAgent = document.getElementById('btn-add-wf-agent');
        if (btnAddAgent) btnAddAgent.onclick = () => this.addNode({ tipo: 'agent' });

        const btnAddCritic = document.getElementById('btn-add-wf-critic');
        if (btnAddCritic) btnAddCritic.onclick = () => this.addNode({ tipo: 'critic' });

        const btnAddRouter = document.getElementById('btn-add-wf-router');
        if (btnAddRouter) btnAddRouter.onclick = () => this.addNode({ tipo: 'router' });

        const btnAddSandbox = document.getElementById('btn-add-wf-sandbox');
        if (btnAddSandbox) btnAddSandbox.onclick = () => this.addNode({ tipo: 'tool' });

        // Botón fallback clásico si existe
        const btnAddGeneric = document.getElementById('btn-add-wf-step');
        if (btnAddGeneric) btnAddGeneric.onclick = () => this.addNode({ tipo: 'agent' });

        // Chips de contexto de muestra
        const chipCode = document.getElementById('wf-chip-code-sample');
        if (chipCode) {
            chipCode.onclick = () => {
                this.initialInputEl.value = `def calcular_estadisticas_ventas(registros):\n    # Bug intencional: no valida nulos ni convierte tipos\n    montos = [float(r['monto']) for r in registros]\n    return {\n        'total': sum(montos),\n        'promedio': sum(montos) / len(montos)\n    }\n\n# Prueba: calcular_estadisticas_ventas([{'monto': '120.5'}, {'monto': None}, {'monto': 30}])`;
            };
        }

        const chipML = document.getElementById('wf-chip-ml-sample');
        if (chipML) {
            chipML.onclick = () => {
                this.initialInputEl.value = `Implementar desde cero con NumPy la función de pérdida Focal Loss con gamma=2.0 y alpha=0.25 para clasificación binaria desbalanceada, incluyendo prueba unitaria numérica que verifique gradientes estables frente a probabilidades extremas (p -> 0 y p -> 1).`;
            };
        }

        const chipDebate = document.getElementById('wf-chip-debate-sample');
        if (chipDebate) {
            chipDebate.onclick = () => {
                this.initialInputEl.value = `Evaluar y contrastar arquitecturas para un sistema de RAG médico: ¿Es preferible utilizar Sparse + Dense Hybrid Search (BM25 + BGE-M3) con Cross-Encoder Reranker, o confiar directamente en un modelo con ventana de contexto de 1M tokens sin chunking?`;
            };
        }

        // Ejecución y parada
        if (this.btnRun) this.btnRun.onclick = () => this.runWorkflow();
        if (this.btnStop) this.btnStop.onclick = () => this.stopWorkflow();

        // Copiar resultado
        if (this.btnCopy) {
            this.btnCopy.onclick = () => {
                if (!this.finalResultText) {
                    alert("Aún no hay un resultado final para copiar.");
                    return;
                }
                navigator.clipboard.writeText(this.finalResultText).then(() => {
                    const original = this.btnCopy.innerHTML;
                    this.btnCopy.innerHTML = '<i class="fa-solid fa-check" style="color:var(--accent-green);"></i> ¡Copiado!';
                    setTimeout(() => { this.btnCopy.innerHTML = original; }, 1800);
                });
            };
        }

        // Exportar e Importar JSON
        const btnExport = document.getElementById('btn-wf-export-json');
        if (btnExport) btnExport.onclick = () => this.exportGraph();

        const btnImport = document.getElementById('btn-wf-import-json');
        const fileImport = document.getElementById('wf-import-file-input');
        if (btnImport && fileImport) {
            btnImport.onclick = () => fileImport.click();
            fileImport.onchange = (e) => {
                const file = e.target.files[0];
                if (file) {
                    this.importGraph(file);
                    fileImport.value = '';
                }
            };
        }
    }

    async fetchModels(preferredModel = null) {
        try {
            const res = await fetch('/api/ai/models');
            const data = await res.json();
            this.models = data.models || ["qwen2.5-coder:7b"];
        } catch (e) {
            console.error("Error fetching models:", e);
            this.models = ["qwen2.5-coder:7b"];
        }

        if (this.stepsContainer) {
            const selects = this.stepsContainer.querySelectorAll('.wf-model-select');
            selects.forEach(select => {
                const currentVal = select.value;
                select.innerHTML = this.models.map(m => `<option value="${m}">${m}</option>`).join('');
                if (currentVal && this.models.includes(currentVal)) {
                    select.value = currentVal;
                } else if (preferredModel && this.models.includes(preferredModel)) {
                    select.value = preferredModel;
                } else if (this.models.length > 0) {
                    select.value = this.models[0];
                }
            });
        }
    }

    async openModal(preset = null) {
        if (!this.modal) return;
        this.modal.style.display = 'flex';
        await this.fetchModels();

        if (this.nodes.length === 0) {
            this.loadTemplate(preset || 'sota_self_healing_code');
        }
    }

    closeModal() {
        if (this.modal) this.modal.style.display = 'none';
        if (this.abortController) {
            this.stopWorkflow();
        }
    }

    // =========================================================================
    // PLANTILLAS PRECONFIGURADAS SOTA
    // =========================================================================
    loadTemplate(templateId) {
        this.nodes = [];
        this.stepsContainer.innerHTML = '';
        this.nodeCounter = 0;

        const defaultModel = (this.models && this.models.length > 0) ? this.models[0] : 'qwen2.5-coder:7b';
        const reasoningModel = this.models.find(m => m.includes('r1') || m.includes('deepseek') || m.includes('qwq')) || defaultModel;

        if (templateId === 'sota_self_healing_code') {
            this.initialInputEl.value = `def calcular_estadisticas(valores, umbral=10.0):\n    # Función con errores de borde, tipos no numéricos y posible división por cero\n    filtrados = [float(v) for v in valores if v > umbral]\n    promedio = sum(filtrados) / len(filtrados)\n    return {'conteo': len(filtrados), 'promedio': promedio}\n\n# Prueba: calcular_estadisticas([15.0, None, "20", 5.0, 10.0])`;

            const n1 = this.addNode({
                id: 'code_gen',
                tipo: 'agent',
                nombre: '💻 Programador Principal',
                rol: 'programmer',
                modelo: defaultModel,
                prompt: 'Corrige e implementa la función solicitada en Python:\n{entrada}\n\nSi hay críticas de un intento anterior:\n{critica}\n\nDevuelve únicamente el bloque de código Python ejecutable sin explicaciones superfluas.',
                temperature: 0.2
            });

            const n2 = this.addNode({
                id: 'code_sandbox',
                tipo: 'tool',
                nombre: '⚡ Sandbox Python (Ejecución Real)',
                rol: 'sandbox',
                prompt: '{anterior}',
                herramienta: 'python_sandbox'
            });

            const n3 = this.addNode({
                id: 'code_critic',
                tipo: 'critic',
                nombre: '🔍 Crítico & Evaluador de Pruebas',
                rol: 'critic',
                modelo: reasoningModel,
                prompt: `Analiza el resultado de la ejecución del sandbox de Python:\n{anterior}\n\nCódigo original y contexto:\n{entrada}\n\nResponde en formato JSON estricto:\n{\n  "aprobado": false si hay error de sintaxis, excepción o resultado incorrecto,\n  "score": número entre 0.0 y 1.0,\n  "problemas": ["descripción de cada falla"],\n  "sugerencias_mejora": ["cómo resolverlo"]\n}`,
                temperature: 0.1,
                loop: { target: n1.id, max_iterations: 3, min_score: 0.9 }
            });

            this.addNode({
                id: 'code_synthesis',
                tipo: 'agent',
                nombre: '✨ Sintetizador de Código Final',
                rol: 'synthesizer',
                modelo: defaultModel,
                prompt: 'Entrega la versión definitiva del código Python validado, limpio, con type hints de Python 3.10+, docstring descriptivo y casos de prueba unitaria assert listos para producción.',
                temperature: 0.2
            });

        } else if (templateId === 'sota_hierarchical_supervisor') {
            this.initialInputEl.value = `Diseñar un pipeline para procesar 10 millones de transacciones financieras diarias con detección de anomalías en tiempo real y persistencia segura.`;

            const nSup = this.addNode({
                id: 'supervisor',
                tipo: 'router',
                nombre: '🔀 Supervisor de Arquitectura',
                rol: 'router',
                modelo: reasoningModel,
                prompt: `Analiza el requerimiento:\n{entrada}\n\nDetermina cuál es el especialista más adecuado para liderar el siguiente paso:\n- "esp_datos": Si el reto principal es volumen, streaming de datos y procesamiento distribuido.\n- "esp_seguridad": Si el foco crítico es auditoría, encriptación y detección de fraude.\n- "esp_backend": Si el foco es APIs, latencia de microservicios y escalado web.\n\nResponde en JSON:\n{\n  "decision": "esp_datos" o "esp_seguridad" o "esp_backend",\n  "razon": "Justificación clara de la elección"\n}`,
                temperature: 0.1
            });

            this.addNode({
                id: 'esp_datos',
                tipo: 'agent',
                nombre: '📊 Especialista Big Data & ML',
                rol: 'analyst',
                modelo: defaultModel,
                prompt: 'Diseña la arquitectura de datos, streaming con Kafka/Flink y modelo de detección de anomalías para:\n{entrada}',
                temperature: 0.3
            });

            this.addNode({
                id: 'esp_seguridad',
                tipo: 'agent',
                nombre: '🛡️ Especialista Ciberseguridad & Fraude',
                rol: 'analyst',
                modelo: defaultModel,
                prompt: 'Diseña los controles criptográficos, análisis de firmas de fraude y auditoría inmutable para:\n{entrada}',
                temperature: 0.3
            });

            this.addNode({
                id: 'sintesis_sup',
                tipo: 'agent',
                nombre: '📑 Síntesis Ejecutiva',
                rol: 'synthesizer',
                modelo: defaultModel,
                prompt: 'Reúne el análisis del especialista seleccionado y genera un blueprint integral de arquitectura listo para ser implementado por el equipo.',
                temperature: 0.2
            });

        } else if (templateId === 'sota_multi_agent_debate') {
            this.initialInputEl.value = `¿Es más eficiente migrar la inferencia de LLMs locales a cuantizaciones extremas (GGUF 2-bit / 3-bit) o recurrir a modelos de menor tamaño pero con precisión completa FP16 (por ejemplo 1.5B en vez de 7B)?`;

            const n1 = this.addNode({
                id: 'debate_tesis',
                tipo: 'agent',
                nombre: '💡 Proponente (Tesis)',
                rol: 'analyst',
                modelo: defaultModel,
                prompt: 'Defiende con argumentos técnicos sólidos y métricas de memoria (VRAM) y perplejidad la siguiente postura sobre:\n{entrada}',
                temperature: 0.6
            });

            const n2 = this.addNode({
                id: 'debate_antitesis',
                tipo: 'agent',
                nombre: '⚡ Opositor (Antítesis)',
                rol: 'analyst',
                modelo: defaultModel,
                prompt: 'Critica y rebate la postura del proponente anterior:\n{anterior}\n\nPresenta los contraargumentos, degradación de razonamiento y benchmarks reales que contradicen su postura.',
                temperature: 0.6
            });

            const n3 = this.addNode({
                id: 'debate_juez',
                tipo: 'critic',
                nombre: '⚖️ Juez Evaluador Dialéctico',
                rol: 'critic',
                modelo: reasoningModel,
                prompt: `Evalúa ambos lados del debate técnico sobre:\n{entrada}\n\nArgumento Tesis:\n{paso:debate_tesis}\n\nArgumento Antítesis:\n{paso:debate_antitesis}\n\nSi ambos argumentos carecen de rigor empírico suficiente, responde en JSON con "aprobado": false para forzar una ronda más profunda.\n{\n  "aprobado": true o false,\n  "score": 0.0 a 1.0,\n  "problemas": ["falacias o falta de evidencia"],\n  "sugerencias_mejora": ["datos empíricos requeridos"]\n}`,
                temperature: 0.2,
                loop: { target: n1.id, max_iterations: 2, min_score: 0.85 }
            });

            this.addNode({
                id: 'debate_consenso',
                tipo: 'agent',
                nombre: '🤝 Dictamen y Consenso Final',
                rol: 'synthesizer',
                modelo: defaultModel,
                prompt: 'Resume el debate, establece el dictamen técnico objetivo y brinda la recomendación definitiva basada en evidencia.',
                temperature: 0.2
            });

        } else if (templateId === 'sota_paper_deconstruction') {
            this.initialInputEl.value = `Algoritmo: Similitud Coseno Vectorizada con NumPy y normalización L2 segura contra normas nulas o divisiones por cero.`;

            const n1 = this.addNode({
                id: 'paper_formula',
                tipo: 'agent',
                nombre: '📐 Analista Matemático de Ecuaciones',
                rol: 'analyst',
                modelo: reasoningModel,
                prompt: 'Deconstruye las fórmulas matemáticas, dimensiones tensoriales y condiciones de frontera para:\n{entrada}\n\nExplica las propiedades algebraicas y cómo evitar indeterminaciones numéricas.',
                temperature: 0.2
            });

            const n2 = this.addNode({
                id: 'paper_implementer',
                tipo: 'agent',
                nombre: '💻 Implementador Numérico Puro',
                rol: 'programmer',
                modelo: defaultModel,
                prompt: 'A partir de la deconstrucción matemática:\n{anterior}\n\nImplementa el código en Python usando exclusivamente NumPy con pruebas unitarias assert integradas. Genera código listo para ejecutar en el sandbox:\n{critica}',
                temperature: 0.2
            });

            const n3 = this.addNode({
                id: 'paper_sandbox',
                tipo: 'tool',
                nombre: '⚡ Sandbox de Verificación Numérica',
                rol: 'sandbox',
                prompt: '{anterior}',
                herramienta: 'python_sandbox'
            });

            const n4 = this.addNode({
                id: 'paper_critic',
                tipo: 'critic',
                nombre: '🔬 Revisor de Rigor Científico',
                rol: 'critic',
                modelo: reasoningModel,
                prompt: `Analiza la ejecución del sandbox numérico:\n{anterior}\n\nResponde en JSON:\n{\n  "aprobado": true si todos los asserts pasaron sin errores,\n  "problemas": ["fallas de precisión numérica"],\n  "sugerencias_mejora": ["ajustes en epsilon o broadcasting"]\n}`,
                temperature: 0.1,
                loop: { target: n2.id, max_iterations: 3, min_score: 0.9 }
            });

            this.addNode({
                id: 'paper_doc',
                tipo: 'agent',
                nombre: '📖 Sintetizador & Documentador Académico',
                rol: 'synthesizer',
                modelo: defaultModel,
                prompt: 'Genera el artículo técnico definitivo: explicación matemática con notación LaTeX, código final probado y guía de complejidad temporal y espacial O(n).',
                temperature: 0.2
            });

        } else {
            // Personalizado básico
            this.addNode({ tipo: 'agent', nombre: 'Agente 1' });
        }

        this.updateLoopTargets();
    }

    // =========================================================================
    // CREACIÓN Y GESTIÓN DE NODOS
    // =========================================================================
    addNode(opts = {}) {
        this.nodeCounter++;
        const index = this.nodes.length + 1;
        const tipo = opts.tipo || 'agent';
        const nodeId = opts.id || `node_${this.nodeCounter}_${Math.random().toString(36).substr(2, 4)}`;

        // Conector visual si ya hay nodos previos
        if (this.nodes.length > 0) {
            const connector = document.createElement('div');
            connector.className = 'wf-connector';
            connector.innerHTML = '<i class="fa-solid fa-arrow-down-long"></i>';
            this.stepsContainer.appendChild(connector);
        }

        const nodeEl = document.createElement('div');
        nodeEl.className = `wf-node node-type-${tipo}`;
        nodeEl.dataset.nodeId = nodeId;
        nodeEl.dataset.tipo = tipo;

        let badgeClass = 'wf-badge-agent';
        let badgeText = 'Agente';
        let icon = 'fa-robot';

        if (tipo === 'critic') {
            badgeClass = 'wf-badge-critic';
            badgeText = 'Bucle Crítico';
            icon = 'fa-rotate';
        } else if (tipo === 'router') {
            badgeClass = 'wf-badge-router';
            badgeText = 'Supervisor';
            icon = 'fa-arrows-split-up-and-left';
        } else if (tipo === 'tool') {
            badgeClass = 'wf-badge-tool';
            badgeText = 'Sandbox Python';
            icon = 'fa-brands fa-python';
        }

        const modelsOptions = (this.models || []).map(m => {
            const sel = (opts.modelo === m) ? 'selected' : '';
            return `<option value="${m}" ${sel}>${m}</option>`;
        }).join('');

        const nombreDefault = opts.nombre || `${badgeText} ${index}`;
        const promptDefault = opts.prompt || (tipo === 'tool' ? '{anterior}' : (index === 1 ? '{entrada}' : 'Procesa y mejora:\n{anterior}'));
        const rolDefault = opts.rol || (tipo === 'critic' ? 'critic' : (tipo === 'router' ? 'router' : (tipo === 'tool' ? 'sandbox' : 'programmer')));
        const tempDefault = opts.temperature !== undefined ? opts.temperature : (tipo === 'critic' ? 0.1 : 0.3);

        nodeEl.innerHTML = `
            <div class="wf-node-header">
                <div class="wf-node-title">
                    <i class="fa-solid ${icon}"></i>
                    <input type="text" class="wf-name-input" value="${nombreDefault}" style="background:transparent; border:none; color:#fff; font-weight:700; font-size:13px; width:220px;" />
                    <span class="wf-node-badge ${badgeClass}">${badgeText}</span>
                </div>
                <div style="display: flex; gap: 4px; align-items: center;">
                    <button type="button" class="btn-move-up tool-btn-icon" style="height:22px; width:22px; font-size:10px;" title="Mover arriba"><i class="fa-solid fa-chevron-up"></i></button>
                    <button type="button" class="btn-move-down tool-btn-icon" style="height:22px; width:22px; font-size:10px;" title="Mover abajo"><i class="fa-solid fa-chevron-down"></i></button>
                    <button type="button" class="btn-remove-node tool-btn-icon" style="height:22px; width:22px; font-size:10px; color:var(--accent-red);" title="Eliminar nodo"><i class="fa-solid fa-trash"></i></button>
                </div>
            </div>

            ${tipo !== 'tool' ? `
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 4px;">
                <div class="wf-node-controls">
                    <label style="font-size: 10.5px; color: var(--text-muted);">Modelo Local Ollama:</label>
                    <select class="wf-model-select">${modelsOptions}</select>
                </div>
                <div class="wf-node-controls">
                    <label style="font-size: 10.5px; color: var(--text-muted);">Rol Especializado:</label>
                    <select class="wf-role-select">
                        <option value="programmer" ${rolDefault === 'programmer' ? 'selected' : ''}>💻 Programador (Código)</option>
                        <option value="analyst" ${rolDefault === 'analyst' ? 'selected' : ''}>📊 Analista / Razonamiento</option>
                        <option value="critic" ${rolDefault === 'critic' ? 'selected' : ''}>🔍 Crítico / Evaluador</option>
                        <option value="router" ${rolDefault === 'router' ? 'selected' : ''}>🔀 Supervisor / Enrutador</option>
                        <option value="synthesizer" ${rolDefault === 'synthesizer' ? 'selected' : ''}>✨ Sintetizador / Editor</option>
                    </select>
                </div>
            </div>
            ` : `
            <div style="background: rgba(166,227,161,0.08); border: 1px solid rgba(166,227,161,0.25); border-radius: 6px; padding: 6px 10px; font-size: 11px; color: var(--accent-green); display: flex; align-items: center; gap: 8px;">
                <i class="fa-solid fa-shield-halved"></i>
                <span>Subproceso Python aislado con captura de STDOUT, STDERR y Traceback (Timeout: 15s).</span>
            </div>
            `}

            <!-- Editor de Prompt / Código con Chips de Variables -->
            <div style="margin-top: 6px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                    <label style="font-size: 10.5px; color: var(--text-muted);">
                        ${tipo === 'tool' ? 'Código a Ejecutar (o {anterior}):' : 'Prompt / Instrucción del Agente:'}
                    </label>
                    <div style="display: flex; gap: 4px;">
                        <button type="button" class="wf-chip-btn insert-chip" data-val="{entrada}" title="Insertar entrada inicial">{entrada}</button>
                        <button type="button" class="wf-chip-btn insert-chip" data-val="{anterior}" title="Insertar salida del nodo previo">{anterior}</button>
                        ${tipo === 'critic' || tipo === 'agent' ? `<button type="button" class="wf-chip-btn insert-chip" data-val="{critica}" title="Insertar retroalimentación">{critica}</button>` : ''}
                    </div>
                </div>
                <textarea class="wf-prompt-input" rows="${tipo === 'tool' ? '2' : '3'}" placeholder="Escribe el prompt o variables del estado...">${promptDefault}</textarea>
            </div>

            <!-- Bucle Recursivo Config (Críticos o Agentes con Loop) -->
            ${tipo === 'critic' || opts.loop ? `
            <div class="wf-loop-config" style="background: rgba(243,139,168,0.08); border: 1px dashed rgba(243,139,168,0.3); border-radius: 6px; padding: 8px 10px; margin-top: 4px;">
                <div style="font-weight: 700; font-size: 11px; color: var(--accent-red); margin-bottom: 6px; display: flex; align-items: center; gap: 6px;">
                    <i class="fa-solid fa-rotate"></i> Configuración de Auto-Corrección Recursiva (Self-Healing Loop)
                </div>
                <div style="display: grid; grid-template-columns: 2fr 1fr; gap: 8px;">
                    <div>
                        <label style="font-size: 10px; color: var(--text-muted);">Si falla o no aprueba, reintentar en:</label>
                        <select class="wf-loop-target-select" style="background: var(--bg-dark); color: #fff; border: 1px solid var(--border-color); border-radius: 4px; padding: 3px 6px; font-size: 11px; width: 100%;">
                            <!-- Se puebla dinámicamente -->
                        </select>
                    </div>
                    <div>
                        <label style="font-size: 10px; color: var(--text-muted);">Vueltas Máx:</label>
                        <input type="number" class="wf-loop-max-iter" min="1" max="6" value="${opts.loop?.max_iterations || 3}" style="background: var(--bg-dark); color: #fff; border: 1px solid var(--border-color); border-radius: 4px; padding: 3px 6px; font-size: 11px; width: 100%;" />
                    </div>
                </div>
            </div>
            ` : ''}

            <!-- Configuración Avanzada Plegable -->
            <button type="button" class="wf-adv-toggle"><i class="fa-solid fa-sliders"></i> Opciones Avanzadas</button>
            <div class="wf-adv-config">
                <div class="wf-node-slider-container">
                    <span>Temperatura: <span class="wf-temp-val">${tempDefault}</span></span>
                    <input type="range" class="wf-temp-slider wf-node-slider" min="0" max="1" step="0.05" value="${tempDefault}">
                </div>
                <div>
                    <label style="font-size: 10px; color: var(--text-muted);">System Prompt Específico (Sobrescribe comportamiento base):</label>
                    <textarea class="wf-sysprompt-input" placeholder="Opcional: Rol o directivas maestras del agente..." rows="2" style="font-size:11px;">${opts.system_prompt || ''}</textarea>
                </div>
            </div>
        `;

        // Eventos internos del nodo
        const btnAdv = nodeEl.querySelector('.wf-adv-toggle');
        const divAdv = nodeEl.querySelector('.wf-adv-config');
        if (btnAdv && divAdv) {
            btnAdv.onclick = () => {
                divAdv.style.display = divAdv.style.display === 'flex' ? 'none' : 'flex';
            };
        }

        const tempSlider = nodeEl.querySelector('.wf-temp-slider');
        const tempVal = nodeEl.querySelector('.wf-temp-val');
        if (tempSlider && tempVal) {
            tempSlider.oninput = () => { tempVal.innerText = tempSlider.value; };
        }

        // Chips de inserción en el textarea
        const promptArea = nodeEl.querySelector('.wf-prompt-input');
        nodeEl.querySelectorAll('.insert-chip').forEach(chip => {
            chip.onclick = () => {
                const val = chip.dataset.val;
                this.insertTextAtCursor(promptArea, val);
            };
        });

        // Botón eliminar
        const btnRemove = nodeEl.querySelector('.btn-remove-node');
        if (btnRemove) {
            btnRemove.onclick = () => {
                this.removeNode(nodeId);
            };
        }

        // Botones reordenar
        const btnUp = nodeEl.querySelector('.btn-move-up');
        if (btnUp) {
            btnUp.onclick = () => this.moveNode(nodeId, -1);
        }
        const btnDown = nodeEl.querySelector('.btn-move-down');
        if (btnDown) {
            btnDown.onclick = () => this.moveNode(nodeId, 1);
        }

        this.stepsContainer.appendChild(nodeEl);

        const nodeObj = {
            id: nodeId,
            tipo,
            element: nodeEl,
            initialOpts: opts
        };
        this.nodes.push(nodeObj);

        this.updateLoopTargets();
        return nodeObj;
    }

    insertTextAtCursor(textarea, text) {
        if (!textarea) return;
        const start = textarea.selectionStart;
        const end = textarea.selectionEnd;
        const before = textarea.value.substring(0, start);
        const after = textarea.value.substring(end, textarea.value.length);
        textarea.value = before + text + after;
        textarea.selectionStart = textarea.selectionEnd = start + text.length;
        textarea.focus();
    }

    removeNode(nodeId) {
        const idx = this.nodes.findIndex(n => n.id === nodeId);
        if (idx === -1) return;

        const nodeObj = this.nodes[idx];
        const el = nodeObj.element;

        // Eliminar conector previo o siguiente
        const prev = el.previousElementSibling;
        const next = el.nextElementSibling;
        if (prev && prev.classList.contains('wf-connector')) prev.remove();
        else if (next && next.classList.contains('wf-connector')) next.remove();

        el.remove();
        this.nodes.splice(idx, 1);
        this.updateLoopTargets();
    }

    moveNode(nodeId, direction) {
        const idx = this.nodes.findIndex(n => n.id === nodeId);
        if (idx === -1) return;
        const targetIdx = idx + direction;
        if (targetIdx < 0 || targetIdx >= this.nodes.length) return;

        // Reordenar array
        const temp = this.nodes[idx];
        this.nodes[idx] = this.nodes[targetIdx];
        this.nodes[targetIdx] = temp;

        // Reconstruir canvas
        this.rebuildCanvasFromNodes();
    }

    rebuildCanvasFromNodes() {
        const savedData = this.serializeCurrentGraph();
        this.stepsContainer.innerHTML = '';
        this.nodes = [];
        savedData.nodos.forEach(n => {
            this.addNode(n);
        });
        this.updateLoopTargets();
    }

    updateLoopTargets() {
        this.nodes.forEach((n, idx) => {
            const targetSelect = n.element.querySelector('.wf-loop-target-select');
            if (targetSelect) {
                const currentVal = targetSelect.value || (n.initialOpts && n.initialOpts.loop ? n.initialOpts.loop.target : null);
                // Puede reintentar en cualquier nodo previo
                const candidatos = this.nodes.slice(0, idx);
                if (candidatos.length === 0) {
                    targetSelect.innerHTML = `<option value="">-- No hay nodos previos --</option>`;
                } else {
                    targetSelect.innerHTML = candidatos.map(c => {
                        const name = c.element.querySelector('.wf-name-input').value || c.id;
                        const sel = (c.id === currentVal) ? 'selected' : '';
                        return `<option value="${c.id}" ${sel}>${name} (${c.id})</option>`;
                    }).join('');
                }
            }
        });
    }

    // =========================================================================
    // EXPORTACIÓN E IMPORTACIÓN DE GRAFOS
    // =========================================================================
    serializeCurrentGraph() {
        const nodos = [];
        this.nodes.forEach((nObj, idx) => {
            const el = nObj.element;
            const nombre = el.querySelector('.wf-name-input')?.value || nObj.id;
            const tipo = nObj.tipo;
            const modelSelect = el.querySelector('.wf-model-select');
            const modelo = modelSelect ? modelSelect.value : null;
            const roleSelect = el.querySelector('.wf-role-select');
            const rol = roleSelect ? roleSelect.value : (tipo === 'tool' ? 'sandbox' : 'programmer');
            const prompt = el.querySelector('.wf-prompt-input')?.value || '';
            const tempSlider = el.querySelector('.wf-temp-slider');
            const temperature = tempSlider ? parseFloat(tempSlider.value) : 0.3;
            const sysArea = el.querySelector('.wf-sysprompt-input');
            const system_prompt = sysArea ? sysArea.value : '';

            let loop = null;
            const loopTargetSelect = el.querySelector('.wf-loop-target-select');
            const loopMaxIter = el.querySelector('.wf-loop-max-iter');
            if (loopTargetSelect && loopTargetSelect.value) {
                loop = {
                    target: loopTargetSelect.value,
                    max_iterations: parseInt(loopMaxIter?.value || '3', 10),
                    min_score: 0.85
                };
            }

            const next_node = (idx + 1 < this.nodes.length) ? this.nodes[idx + 1].id : null;

            nodos.push({
                id: nObj.id,
                nombre,
                tipo,
                rol,
                modelo,
                prompt,
                temperature,
                system_prompt,
                loop,
                herramienta: tipo === 'tool' ? 'python_sandbox' : null,
                next_node
            });
        });

        return {
            titulo: "Flujo de Agentes Prig IDE",
            version: "2.0-sota",
            nodo_inicial: nodos.length > 0 ? nodos[0].id : null,
            entrada_inicial: this.initialInputEl.value,
            nodos
        };
    }

    exportGraph() {
        const grafo = this.serializeCurrentGraph();
        const jsonStr = JSON.stringify(grafo, null, 2);
        const blob = new Blob([jsonStr], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `prig_grafo_agentes_${new Date().toISOString().slice(0, 10)}.json`;
        a.click();
        URL.revokeObjectURL(url);
    }

    importGraph(file) {
        const reader = new FileReader();
        reader.onload = (e) => {
            try {
                const data = JSON.parse(e.target.result);
                if (data.entrada_inicial) this.initialInputEl.value = data.entrada_inicial;
                if (Array.isArray(data.nodos) && data.nodos.length > 0) {
                    this.stepsContainer.innerHTML = '';
                    this.nodes = [];
                    data.nodos.forEach(n => this.addNode(n));
                    this.updateLoopTargets();
                } else {
                    alert("El archivo no contiene un grafo de nodos válido.");
                }
            } catch (err) {
                alert("Error al leer el archivo JSON: " + err.message);
            }
        };
        reader.readAsText(file);
    }

    // =========================================================================
    // MOTOR DE EJECUCIÓN Y STREAMING NDJSON
    // =========================================================================
    async runWorkflow() {
        const graphDef = this.serializeCurrentGraph();
        if (graphDef.nodos.length === 0) {
            alert("Agrega al menos un nodo al flujo antes de iniciar.");
            return;
        }

        this.finalResultText = "";
        this.resultsContainer.innerHTML = '';
        this.iterationTabsEl.innerHTML = '';
        this.iterationTabsEl.style.display = 'none';
        this.currentIteration = 1;

        this.statusEl.innerHTML = '<i class="fa-solid fa-spinner fa-spin" style="color:var(--accent-yellow);"></i> Inicializando ejecución distribuida del grafo...';
        this.statusEl.style.borderLeftColor = 'var(--accent-yellow)';
        this.statsEl.innerText = '';

        if (this.btnRun) this.btnRun.disabled = true;
        if (this.btnStop) this.btnStop.style.display = 'inline-flex';

        this.startTime = Date.now();
        this.timerInterval = setInterval(() => {
            const elapsed = ((Date.now() - this.startTime) / 1000).toFixed(1);
            if (this.timerEl) this.timerEl.innerText = `${elapsed}s`;
        }, 100);

        this.abortController = new AbortController();

        try {
            const res = await fetch('/api/flujos/ejecutar', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                signal: this.abortController.signal,
                body: JSON.stringify({
                    flujo: graphDef,
                    entrada: graphDef.entrada_inicial
                })
            });

            if (!res.ok) {
                const errDetail = typeof window.prigErrorDetail === 'function' ? await window.prigErrorDetail(res) : await res.text();
                throw new Error(errDetail);
            }

            const reader = res.body.getReader();
            const decoder = new TextDecoder('utf-8');
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop(); // Guarda el fragmento incompleto

                for (const line of lines) {
                    if (!line.trim()) continue;
                    try {
                        const event = JSON.parse(line);
                        this.handleStreamEvent(event);
                    } catch (e) {
                        console.warn("Línea NDJSON no parseable:", line, e);
                    }
                }
            }

            // Procesar residuo si quedó
            if (buffer.trim()) {
                try {
                    const event = JSON.parse(buffer);
                    this.handleStreamEvent(event);
                } catch (e) { }
            }

        } catch (err) {
            if (err.name === 'AbortError') {
                this.statusEl.innerHTML = '<i class="fa-solid fa-ban" style="color:var(--accent-red);"></i> Ejecución cancelada por el usuario.';
            } else {
                this.statusEl.innerHTML = `<i class="fa-solid fa-triangle-exclamation" style="color:var(--accent-red);"></i> Error: ${err.message}`;
                const errCard = document.createElement('div');
                errCard.style.cssText = 'background: rgba(243,139,168,0.12); border-left: 4px solid var(--accent-red); padding: 10px; border-radius: 4px; margin-top: 10px; font-family: monospace; font-size: 11.5px;';
                errCard.innerText = err.message;
                this.resultsContainer.appendChild(errCard);
            }
        } finally {
            this.finishExecution();
        }
    }

    stopWorkflow() {
        if (this.abortController) {
            this.abortController.abort();
            this.abortController = null;
        }
        this.finishExecution();
    }

    finishExecution() {
        if (this.timerInterval) {
            clearInterval(this.timerInterval);
            this.timerInterval = null;
        }
        if (this.btnRun) this.btnRun.disabled = false;
        if (this.btnStop) this.btnStop.style.display = 'none';

        // Remover clases de ejecución en nodos
        document.querySelectorAll('.wf-node.running').forEach(el => el.classList.remove('running'));
    }

    handleStreamEvent(evt) {
        const tipo = evt.tipo || evt.status;

        // 1. GRAFO INICIO
        if (tipo === 'grafo_inicio') {
            this.statusEl.innerHTML = `<i class="fa-solid fa-play" style="color:var(--accent-purple);"></i> Ejecutando: <strong>${evt.titulo}</strong> (${evt.nodos_totales} nodos)...`;
            return;
        }

        // 2. NODO INICIO
        if (tipo === 'nodo_inicio' || tipo === 'running') {
            const nodeId = evt.id;
            const nodeName = evt.nombre || evt.name || nodeId;
            const nodeModel = evt.modelo || evt.model || 'Ollama';
            const tipoNodo = evt.tipo_nodo || 'agent';

            // Actualizar visualmente el nodo en el canvas
            document.querySelectorAll('.wf-node').forEach(el => el.classList.remove('running'));
            const nodeCard = document.querySelector(`.wf-node[data-node-id="${nodeId}"]`);
            if (nodeCard) {
                nodeCard.classList.add('running');
                nodeCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }

            this.statusEl.innerHTML = `<i class="fa-solid fa-spinner fa-spin" style="color:var(--accent-yellow);"></i> Ejecutando nodo: <strong>${nodeName}</strong> [${nodeModel}] (Vuelta ${evt.iteracion || 1})...`;

            // Crear tarjeta en el Cockpit
            const card = document.createElement('div');
            card.id = `cockpit-node-${nodeId}-${evt.iteracion || 1}`;
            card.style.cssText = 'background: rgba(0,0,0,0.2); border: 1px solid var(--border-color); border-radius: 6px; padding: 12px; margin-bottom: 12px;';

            let icon = 'fa-robot';
            let color = 'var(--accent-purple)';
            if (tipoNodo === 'critic') { icon = 'fa-rotate'; color = 'var(--accent-red)'; }
            else if (tipoNodo === 'router') { icon = 'fa-arrows-split-up-and-left'; color = '#89dceb'; }
            else if (tipoNodo === 'tool') { icon = 'fa-brands fa-python'; color = 'var(--accent-green)'; }

            card.innerHTML = `
                <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid rgba(255,255,255,0.06); padding-bottom:6px; margin-bottom:8px;">
                    <div style="font-weight:700; font-size:12px; color:#fff; display:flex; align-items:center; gap:8px;">
                        <i class="fa-solid ${icon}" style="color:${color};"></i>
                        <span>${nodeName}</span>
                        <span style="font-size:10px; background:rgba(255,255,255,0.06); padding:2px 6px; border-radius:8px; color:var(--text-muted);">${nodeModel}</span>
                    </div>
                    <span style="font-size:10px; color:var(--text-muted);">Iteración ${evt.iteracion || 1}</span>
                </div>
                <div class="cockpit-output-stream" style="font-size:12px; line-height:1.5; color:var(--text-main); font-family:monospace; white-space:pre-wrap;"></div>
            `;

            this.resultsContainer.appendChild(card);
            this.resultsContainer.scrollTop = this.resultsContainer.scrollHeight;
            this.activeOutputNodeEl = card.querySelector('.cockpit-output-stream');
            return;
        }

        // 3. TOKEN STREAMING
        if (tipo === 'node_token') {
            if (this.activeOutputNodeEl) {
                this.activeOutputNodeEl.textContent += evt.token;
                this.resultsContainer.scrollTop = this.resultsContainer.scrollHeight;
            }
            return;
        }

        // 4. TOOL INICIO
        if (tipo === 'tool_inicio') {
            if (this.activeOutputNodeEl) {
                this.activeOutputNodeEl.innerHTML = '<span style="color:var(--accent-green);"><i class="fa-solid fa-spinner fa-spin"></i> Ejecutando código en subproceso Python...</span>';
            }
            return;
        }

        // 5. TOOL FIN
        if (tipo === 'tool_fin') {
            if (this.activeOutputNodeEl) {
                const exito = evt.exito;
                const statusBadge = exito
                    ? '<span style="background:rgba(166,227,161,0.2); color:var(--accent-green); padding:2px 8px; border-radius:10px; font-weight:700; font-size:10.5px;">EXITOSO (Code: 0)</span>'
                    : '<span style="background:rgba(243,139,168,0.2); color:var(--accent-red); padding:2px 8px; border-radius:10px; font-weight:700; font-size:10.5px;">FALLÓ (Traceback)</span>';

                let cuerpo = `<div style="margin-bottom:8px;">${statusBadge}</div>`;
                cuerpo += `<pre style="background:var(--bg-dark); padding:10px; border-radius:6px; border:1px solid var(--border-color); color:${exito ? 'var(--text-main)' : 'var(--accent-red)'}; font-size:11.5px; overflow-x:auto;">${this.escapeHtml(evt.salida)}</pre>`;
                this.activeOutputNodeEl.innerHTML = cuerpo;
                this.activeOutputNodeEl.style.whiteSpace = 'normal';
                this.resultsContainer.scrollTop = this.resultsContainer.scrollHeight;
            }
            return;
        }

        // 6. NODO FIN
        if (tipo === 'nodo_fin' || tipo === 'completed') {
            const nodeId = evt.id;
            const nodeCard = document.querySelector(`.wf-node[data-node-id="${nodeId}"]`);
            if (nodeCard) {
                nodeCard.classList.remove('running');
                nodeCard.classList.add('completed');
            }

            const salida = evt.salida || evt.result || '';
            if (this.activeOutputNodeEl) {
                // Renderizar markdown profesional con KaTeX
                const htmlContent = (typeof window.prigRenderMarkdown === 'function')
                    ? window.prigRenderMarkdown(salida)
                    : `<div style="white-space:pre-wrap;">${this.escapeHtml(salida)}</div>`;

                let jsonBlock = '';
                if (evt.datos_json && typeof evt.datos_json === 'object') {
                    const d = evt.datos_json;
                    const aprobado = d.aprobado !== undefined ? d.aprobado : (d.score !== undefined ? d.score >= 0.8 : null);
                    let badge = '';
                    if (aprobado === true) badge = '<span style="background:rgba(166,227,161,0.2); color:var(--accent-green); padding:2px 8px; border-radius:10px; font-weight:700; font-size:10px;">APROBADO</span>';
                    else if (aprobado === false) badge = '<span style="background:rgba(243,139,168,0.2); color:var(--accent-red); padding:2px 8px; border-radius:10px; font-weight:700; font-size:10px;">RECHAZADO</span>';

                    jsonBlock = `
                        <div style="background: rgba(0,0,0,0.3); border: 1px solid var(--border-color); border-radius: 6px; padding: 8px 12px; margin-top: 10px; font-size: 11.5px;">
                            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                                <strong style="color:var(--accent-yellow);">Evaluación Estructurada:</strong>
                                ${badge}
                            </div>
                            ${d.score !== undefined ? `<div style="color:var(--text-muted);">Score: <strong>${d.score}</strong></div>` : ''}
                            ${d.problemas && d.problemas.length > 0 ? `<div style="color:var(--accent-red); margin-top:4px;">Problemas:<ul style="margin:2px 0 2px 18px;">${d.problemas.map(p => `<li>${p}</li>`).join('')}</ul></div>` : ''}
                            ${d.sugerencias_mejora && d.sugerencias_mejora.length > 0 ? `<div style="color:var(--accent-blue); margin-top:4px;">Sugerencias:<ul style="margin:2px 0 2px 18px;">${d.sugerencias_mejora.map(s => `<li>${s}</li>`).join('')}</ul></div>` : ''}
                        </div>
                    `;
                }

                this.activeOutputNodeEl.innerHTML = `<div class="prig-markdown-body" style="font-family:inherit;">${htmlContent}</div>${jsonBlock}`;
                this.activeOutputNodeEl.style.whiteSpace = 'normal';
                this.resultsContainer.scrollTop = this.resultsContainer.scrollHeight;
            }
            return;
        }

        // 7. VUELTA RECURSIVA (Self-Reflection Loop)
        if (tipo === 'vuelta_recursiva') {
            const vuelta = evt.vuelta;
            const maxVueltas = evt.max_vueltas;
            const desde = evt.desde;
            const hacia = evt.hacia;

            this.statusEl.innerHTML = `<i class="fa-solid fa-rotate fa-spin" style="color:var(--accent-red);"></i> Bucle de Corrección: Reintentando en <strong>${hacia}</strong> (Intento ${vuelta} de ${maxVueltas})...`;

            const alertDiv = document.createElement('div');
            alertDiv.style.cssText = 'background: rgba(243,139,168,0.15); border: 1px solid var(--accent-red); border-radius: 6px; padding: 10px 14px; margin: 12px 0; font-size: 12px; color: #fff; display: flex; align-items: flex-start; gap: 10px;';
            alertDiv.innerHTML = `
                <i class="fa-solid fa-rotate" style="color:var(--accent-red); font-size:16px; margin-top:2px;"></i>
                <div style="flex:1;">
                    <strong>Auto-Corrección Activada (Intento ${vuelta}/${maxVueltas}):</strong> El evaluador rechazó la solución previa y transfirió la crítica a <code>${hacia}</code>.
                    ${evt.motivo ? `<div style="margin-top:6px; font-size:11px; background:rgba(0,0,0,0.3); padding:6px 10px; border-radius:4px; font-family:monospace; color:var(--text-muted);">${this.escapeHtml(evt.motivo)}</div>` : ''}
                </div>
            `;
            this.resultsContainer.appendChild(alertDiv);
            this.resultsContainer.scrollTop = this.resultsContainer.scrollHeight;

            // Actualizar tabs de iteración
            this.iterationTabsEl.style.display = 'flex';
            const tabBtn = document.createElement('button');
            tabBtn.type = 'button';
            tabBtn.className = 'wf-iteration-tab active';
            tabBtn.innerText = `Iteración ${vuelta}`;
            this.iterationTabsEl.appendChild(tabBtn);
            return;
        }

        // 8. ENRUTAMIENTO DINÁMICO (Supervisor)
        if (tipo === 'enrutamiento_dinamico') {
            const routerDiv = document.createElement('div');
            routerDiv.style.cssText = 'background: rgba(137,220,235,0.12); border-left: 4px solid #89dceb; border-radius: 4px; padding: 8px 12px; margin: 10px 0; font-size: 11.5px;';
            routerDiv.innerHTML = `
                <div style="color:#89dceb; font-weight:700; display:flex; align-items:center; gap:6px;">
                    <i class="fa-solid fa-arrows-split-up-and-left"></i> Enrutamiento Dinámico del Supervisor:
                </div>
                <div style="margin-top:4px; color:#fff;">Destino elegido: <strong>${evt.destino}</strong></div>
                <div style="font-size:11px; color:var(--text-muted); margin-top:2px;">Razón: ${this.escapeHtml(evt.razon || '')}</div>
            `;
            this.resultsContainer.appendChild(routerDiv);
            this.resultsContainer.scrollTop = this.resultsContainer.scrollHeight;
            return;
        }

        // 9. GRAFO FIN
        if (tipo === 'grafo_fin' || tipo === 'finished') {
            const resultadoFinal = evt.resultado_final || evt.final_result || '';
            this.finalResultText = resultadoFinal;

            this.statusEl.innerHTML = `<i class="fa-solid fa-circle-check" style="color:var(--accent-green);"></i> ¡Grafo completado con éxito! (${evt.segundos_totales || 0}s, ${evt.pasos_totales || 0} pasos ejecutados)`;
            this.statusEl.style.borderLeftColor = 'var(--accent-green)';
            this.statsEl.innerText = `${evt.pasos_totales || ''} pasos · ${evt.segundos_totales || ''}s`;

            const finalDiv = document.createElement('div');
            finalDiv.style.cssText = 'margin-top: 18px; padding: 14px; background: rgba(166,227,161,0.08); border: 1px solid rgba(166,227,161,0.3); border-radius: 8px;';

            const renderedFinal = (typeof window.prigRenderMarkdown === 'function')
                ? window.prigRenderMarkdown(resultadoFinal)
                : `<div style="white-space:pre-wrap;">${this.escapeHtml(resultadoFinal)}</div>`;

            finalDiv.innerHTML = `
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; border-bottom:1px solid rgba(166,227,161,0.2); padding-bottom:6px;">
                    <div style="font-weight:700; color:var(--accent-green); font-size:13px; display:flex; align-items:center; gap:8px;">
                        <i class="fa-solid fa-flag-checkered"></i> ENTREGA FINAL DEL FLUJO MULTI-AGENTE
                    </div>
                </div>
                <div class="prig-markdown-body" style="font-size:12.5px; line-height:1.6;">${renderedFinal}</div>
            `;

            this.resultsContainer.appendChild(finalDiv);
            this.resultsContainer.scrollTop = this.resultsContainer.scrollHeight;
            return;
        }

        // 10. ERROR
        if (tipo === 'error' || tipo === 'nodo_error') {
            const msg = evt.mensaje || evt.error || 'Error desconocido en el flujo';
            this.statusEl.innerHTML = `<i class="fa-solid fa-circle-exclamation" style="color:var(--accent-red);"></i> Error: ${this.escapeHtml(msg)}`;
            this.statusEl.style.borderLeftColor = 'var(--accent-red)';
            return;
        }
    }

    escapeHtml(text) {
        if (!text) return '';
        return String(text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }
}

// Inicialización global
document.addEventListener('DOMContentLoaded', () => {
    window.agentWorkflowMgr = new AgentWorkflowManager();
});
