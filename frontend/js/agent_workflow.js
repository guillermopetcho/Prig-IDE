class AgentWorkflowManager {
    constructor() {
        this.modal = document.getElementById('modal-agent-workflow');
        this.stepsContainer = document.getElementById('wf-steps-container');
        this.models = [];
        this.stepCount = 0;
        
        this.initEvents();
    }

    initEvents() {
        const btnClose = document.getElementById('btn-close-workflow-modal');
        if (btnClose) btnClose.onclick = () => this.closeModal();

        const btnAdd = document.getElementById('btn-add-wf-step');
        if (btnAdd) btnAdd.onclick = () => this.addStep();

        const btnRun = document.getElementById('btn-run-workflow');
        if (btnRun) btnRun.onclick = () => this.runWorkflow();

        // Close on escape
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.modal && this.modal.style.display === 'flex') {
                this.closeModal();
            }
        });
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

    async openModal() {
        if (!this.modal) return;
        this.modal.style.display = 'flex';
        await this.fetchModels();
        if (this.stepCount === 0) {
            this.addStep(); // Add first step by default
        }
    }

    closeModal() {
        if (this.modal) this.modal.style.display = 'none';
    }

    addStep() {
        this.stepCount++;
        const stepId = this.stepCount;
        
        // Add connector if not the first step
        if (this.stepCount > 1) {
            const connector = document.createElement('div');
            connector.className = 'wf-connector';
            connector.innerHTML = '<i class="fa-solid fa-arrow-right-long"></i>';
            this.stepsContainer.appendChild(connector);
        }
        
        const stepDiv = document.createElement('div');
        stepDiv.className = 'wf-node';
        
        const modelsOptions = this.models.map(m => `<option value="${m}">${m}</option>`).join('');
        
        stepDiv.innerHTML = `
            <div class="wf-node-header">
                <span class="wf-node-title"><i class="fa-solid fa-robot"></i> <span class="node-id-lbl">Nodo ${stepId}</span></span>
                <button class="btn-remove-step tool-btn-icon" style="height: 24px; width: 24px; font-size: 11px;" title="Eliminar nodo"><i class="fa-solid fa-trash"></i></button>
            </div>
            
            <div class="wf-node-controls">
                <input type="text" class="wf-name-input wf-node-input" placeholder="Nombre (ej. Programador Frontend)" value="Agente ${stepId}" />
            </div>

            <div class="wf-node-controls">
                <label style="font-size: 11px; color: var(--text-muted);">Modelo Local:</label>
                <select class="wf-model-select">${modelsOptions}</select>
            </div>
            
            <div class="wf-node-controls">
                <label style="font-size: 11px; color: var(--text-muted);">Rol del Agente:</label>
                <select class="wf-role-select">
                    <option value="programmer">💻 Programador (Generar Código)</option>
                    <option value="explainer">📖 Analista (Explicar/Razonar)</option>
                </select>
            </div>
            
            <textarea class="wf-prompt-input" placeholder="Ej: Traduce el código a Python..." rows="3"></textarea>

            <button class="wf-adv-toggle">⚙️ Configuración Avanzada</button>
            <div class="wf-adv-config">
                <div class="wf-node-slider-container">
                    <span>Temp: <span class="wf-temp-val">0.3</span></span>
                    <input type="range" class="wf-temp-slider wf-node-slider" min="0" max="1" step="0.1" value="0.3">
                </div>
                <label style="font-size: 11px; color: var(--text-muted);">System Prompt (Opcional):</label>
                <textarea class="wf-sysprompt-input" placeholder="Sobrescribe el comportamiento base de este agente..." rows="3" style="font-size:11px;"></textarea>
            </div>
        `;
        
        const btnAdv = stepDiv.querySelector('.wf-adv-toggle');
        const divAdv = stepDiv.querySelector('.wf-adv-config');
        btnAdv.onclick = () => {
            divAdv.style.display = divAdv.style.display === 'flex' ? 'none' : 'flex';
        };

        const tempSlider = stepDiv.querySelector('.wf-temp-slider');
        const tempVal = stepDiv.querySelector('.wf-temp-val');
        tempSlider.oninput = () => { tempVal.innerText = tempSlider.value; };

        const btnRemove = stepDiv.querySelector('.btn-remove-step');
        btnRemove.onclick = () => {
            // Remove the node
            const prevConnector = stepDiv.previousElementSibling;
            const nextConnector = stepDiv.nextElementSibling;
            
            if (prevConnector && prevConnector.className.includes('wf-connector')) {
                prevConnector.remove();
            } else if (nextConnector && nextConnector.className.includes('wf-connector')) {
                nextConnector.remove();
            }
            stepDiv.remove();
            this.reindexSteps();
        };

        this.stepsContainer.appendChild(stepDiv);
        // Scroll far right
        this.stepsContainer.scrollLeft = this.stepsContainer.scrollWidth;
    }

    reindexSteps() {
        const steps = this.stepsContainer.querySelectorAll('.wf-node');
        steps.forEach((step, idx) => {
            step.querySelector('.node-id-lbl').innerText = `Nodo ${idx + 1}`;
        });
        this.stepCount = steps.length;
    }

    async runWorkflow() {
        const initialInput = document.getElementById('wf-initial-input').value;
        const stepEls = this.stepsContainer.querySelectorAll('.wf-node');
        
        const steps = [];
        stepEls.forEach((stepEl) => {
            const name = stepEl.querySelector('.wf-name-input').value || 'Agente';
            const model = stepEl.querySelector('.wf-model-select').value;
            const role = stepEl.querySelector('.wf-role-select').value;
            const prompt = stepEl.querySelector('.wf-prompt-input').value;
            const temperature = parseFloat(stepEl.querySelector('.wf-temp-slider').value);
            const system_prompt = stepEl.querySelector('.wf-sysprompt-input').value;
            steps.push({ name, model, role, prompt, temperature, system_prompt });
        });

        if (steps.length === 0) {
            alert("Agrega al menos un paso al flujo.");
            return;
        }

        const resultsContainer = document.getElementById('wf-results-container');
        const statusEl = document.getElementById('wf-execution-status');
        
        resultsContainer.innerHTML = '';
        statusEl.innerText = "Iniciando ejecución del flujo...";
        statusEl.style.color = 'var(--accent-yellow)';

        try {
            const res = await fetch('/api/ai/workflow/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ initial_input: initialInput, steps })
            });

            // Una respuesta en flujo también puede fallar antes de emitir nada:
            // sin esto, res.body.getReader() sobre un 500 dejaba el panel en blanco.
            if (!res.ok) throw new Error(await prigErrorDetail(res));

            const reader = res.body.getReader();
            const decoder = new TextDecoder("utf-8");

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                const chunkStr = decoder.decode(value);
                const lines = chunkStr.split('\n');
                
                for (const line of lines) {
                    if (!line.trim()) continue;
                    try {
                        const data = JSON.parse(line);
                        
                        if (data.status === 'running') {
                            statusEl.innerText = `Ejecutando ${data.name || 'Agente'} (${data.model})...`;
                        } else if (data.status === 'completed') {
                            const resultDiv = document.createElement('div');
                            resultDiv.style.cssText = "margin-bottom: 12px; padding-bottom: 12px; border-bottom: 1px dashed var(--border-color);";
                            const contentHtml = (typeof marked !== 'undefined') ? marked.parse(data.result) : data.result;
                            resultDiv.innerHTML = `<strong style="color:var(--accent-green);">Resultado ${data.name || ('Paso ' + (data.step + 1))}:</strong>\n\n<div style="margin-top:8px;">${contentHtml}</div>`;
                            resultsContainer.appendChild(resultDiv);
                            resultsContainer.scrollTop = resultsContainer.scrollHeight;
                        } else if (data.status === 'finished') {
                            statusEl.innerText = "¡Flujo completado con éxito!";
                            statusEl.style.color = 'var(--accent-green)';
                            
                            const finalDiv = document.createElement('div');
                            finalDiv.style.cssText = "margin-top: 15px; padding: 10px; background: rgba(166,227,161,0.1); border-radius: 5px;";
                            const finalHtml = (typeof marked !== 'undefined') ? marked.parse(data.final_result) : data.final_result;
                            finalDiv.innerHTML = `<strong style="color:var(--accent-green);">RESULTADO FINAL:</strong>\n\n<div style="margin-top:8px;">${finalHtml}</div>`;
                            resultsContainer.appendChild(finalDiv);
                            resultsContainer.scrollTop = resultsContainer.scrollHeight;
                        }
                    } catch (e) {
                        console.error("Error parseando línea ndjson:", line, e);
                    }
                }
            }
        } catch (e) {
            statusEl.innerText = "Error ejecutando el flujo: " + e;
            statusEl.style.color = 'var(--accent-red)';
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    window.agentWorkflowMgr = new AgentWorkflowManager();
});
