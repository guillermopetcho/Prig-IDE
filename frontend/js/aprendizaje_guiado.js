/**
 * Aprendizaje Guiado: el sistema único de rutas de estudio.
 *
 * Sustituye a "Recorrido" (tres agentes) y "Seguimiento" (un agente), que
 * duplicaban interfaz, almacenamiento y seguimiento del progreso. Ahora hay un solo
 * modelo de ruta con bloques, y la diferencia es la PROFUNDIDAD de la generación:
 *   · rápido   — un agente organiza tus temas en bloques
 *   · profundo — tres agentes analizan tu biblioteca y generan cuadernos
 */
class AprendizajeGuiadoManager {
    constructor() {
        // rapido = un agente ordena tus temas · profundo = tres agentes analizan la biblioteca
        this.modo = 'rapido';
        this.currentData = null;
        this.completedBlocks = new Set();
        this.abortController = null;
        this.isGenerating = false;
        this._timerInterval = null;
        this.init();
    }

    // Dynamic Getters for Live DOM Access (Prevents null/stale references)
    get modal() { return document.getElementById('modal-seguimiento'); }
    get btnGenerate() { return document.getElementById('btn-generate-seguimiento'); }
    get btnCancel() { return document.getElementById('btn-cancel-seguimiento'); }
    get goalInput() { return document.getElementById('seguimiento-goal'); }
    get topicsInput() { return document.getElementById('seguimiento-topics'); }
    get levelInput() { return document.getElementById('seguimiento-level'); }
    get focusInput() { return document.getElementById('seguimiento-focus'); }
    get modelInput() { return document.getElementById('seguimiento-model'); }
    get canvasContainer() { return document.getElementById('seguimiento-canvas-container'); }
    get canvasContent() { return document.getElementById('seguimiento-canvas-content'); }
    get svgOverlay() { return document.getElementById('seguimiento-svg-overlay'); }
    get progressBar() { return document.getElementById('seguimiento-progress-bar'); }
    get progressFill() { return document.getElementById('seguimiento-progress-fill'); }
    get progressPct() { return document.getElementById('seguimiento-pct'); }
    get historyList() { return document.getElementById('seguimiento-history-list'); }

    init() {
        const btn = this.btnGenerate;
        if (btn) {
            btn.onclick = (e) => {
                if (e) e.preventDefault();
                this.generateSeguimiento();
            };
        }

        const btnCancel = this.btnCancel;
        if (btnCancel) {
            btnCancel.onclick = (e) => {
                if (e) e.preventDefault();
                this.cancelGeneration();
            };
        }

        const container = this.canvasContainer;
        if (container) {
            container.addEventListener('scroll', () => this.drawConnectors());
            window.addEventListener('resize', () => this.drawConnectors());
        }

        this.loadModels();
    }

    openModal() {
        this.initModoSelector();
        const m = this.modal;
        if (m) {
            m.style.display = 'flex';
            this.fetchHistory();
            this.loadModels();
        }
    }

    closeModal() {
        const m = this.modal;
        if (m) m.style.display = 'none';
    }

    async loadModels(preferredModel = null) {
        const modelEl = this.modelInput;
        if (!modelEl) return;
        try {
            const res = await fetch('/api/ai/status');
            const data = await res.json();
            const models = (data.models && data.models.length > 0) ? data.models : ['qwen2.5-coder:7b'];
            
            const currVal = preferredModel || modelEl.value;
            modelEl.innerHTML = '';
            models.forEach(m => {
                const opt = document.createElement('option');
                opt.value = m;
                opt.textContent = m;
                opt.style.backgroundColor = '#1e1e2e';
                opt.style.color = '#cdd6f4';
                modelEl.appendChild(opt);
            });

            if (currVal && models.includes(currVal)) {
                modelEl.value = currVal;
            } else if (models.includes('qwen2.5-coder:7b')) {
                modelEl.value = 'qwen2.5-coder:7b';
            }
        } catch (err) {
            console.error('Error al cargar modelos de Ollama para Seguimiento:', err);
        }
    }

    async fetchHistory() {
        const hl = this.historyList;
        if (!hl) return;
        try {
            // /api/guided/list responde {paths: [...]}, no un array suelto.
            const payload = await prigJson(await fetch('/api/guided/list'));
            const data = Array.isArray(payload) ? payload : (payload.paths || []);

            if (data.length === 0) {
                hl.innerHTML = '<div style="text-align: center; color: var(--text-muted); font-size: 12px; margin-top: 20px;">No tienes listas de aprendizaje guardadas aún.</div>';
                return;
            }
            
            let html = '';
            data.forEach(item => {
                const fecha = item.created_at ? new Date(item.created_at) : null;
                const date = (fecha && !isNaN(fecha)) ? fecha.toLocaleDateString() : '—';
                html += `
                    <div style="background: rgba(255,255,255,0.05); border: 1px solid var(--border-color); border-radius: 6px; padding: 10px; display: flex; flex-direction: column; gap: 6px; cursor: pointer; transition: background 0.2s;" onclick="window.guiadoMgr.loadSeguimiento('${item.id}')" onmouseover="this.style.background='rgba(255,255,255,0.1)'" onmouseout="this.style.background='rgba(255,255,255,0.05)'">
                        <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                            <strong style="color: var(--accent-blue); font-size: 13px; margin-right: 10px;">${item.goal}</strong>
                            <button onclick="event.stopPropagation(); window.guiadoMgr.deleteSeguimiento('${item.id}')" style="background: none; border: none; color: var(--accent-red); cursor: pointer;" title="Eliminar"><i class="fa-solid fa-trash"></i></button>
                        </div>
                        <div style="display: flex; justify-content: space-between; align-items: center; font-size: 11px; color: var(--text-muted);">
                            <span><i class="fa-regular fa-calendar"></i> ${date}</span>
                            <span>Progreso: ${item.progress || 0}%</span>
                        </div>
                        <div style="width: 100%; height: 4px; background: rgba(0,0,0,0.3); border-radius: 2px; overflow: hidden; margin-top: 4px;">
                            <div style="width: ${item.progress || 0}%; height: 100%; background: var(--accent-green);"></div>
                        </div>
                    </div>
                `;
            });
            hl.innerHTML = html;
        } catch (err) {
            console.error(err);
            const motivo = String(err && err.message ? err.message : err)
                .replace(/&/g, '&amp;').replace(/</g, '&lt;');
            hl.innerHTML = `<div style="color: var(--accent-red); font-size: 12px; line-height: 1.5;">
                No se pudo cargar la lista de rutas.<br><span style="color: var(--text-muted); font-size: 11px;">${motivo}</span>
                <button onclick="window.guiadoMgr.fetchHistory()" style="display:block; margin-top:8px; font-size:11px; padding:3px 8px; border-radius:4px; background: rgba(137,180,250,0.15); color: var(--accent-blue); border:1px solid rgba(137,180,250,0.35); cursor:pointer;">Reintentar</button>
            </div>`;
        }
    }

    async loadSeguimiento(id) {
        try {
            if (this.canvasContent) {
                this.canvasContent.innerHTML = '<div style="text-align: center; color: var(--accent-yellow); margin-top: 40px;"><i class="fa-solid fa-spinner fa-spin fa-3x"></i><p style="margin-top: 15px; font-weight: bold;">Cargando ruta...</p></div>';
            }
            this.clearSVGConnectors();
            if (this.progressBar) this.progressBar.style.display = 'none';

            const res = await fetch(`/api/guided/${id}`);
            if (!res.ok) throw new Error(await prigErrorDetail(res));
            const data = await res.json();
            
            this.currentData = data;
            this.completedBlocks = new Set(data.completed_blocks || []);
            
            if (this.goalInput) this.goalInput.value = data.goal || "";
            if (this.topicsInput) this.topicsInput.value = data.topics_raw || "";

            this.renderCanvas(data);
            this.updateProgressUI();
            if (this.progressBar) this.progressBar.style.display = 'flex';
        } catch (err) {
            console.error(err);
            if (this.canvasContent) {
                this.canvasContent.innerHTML = `<div style="color: var(--accent-red); padding: 15px;">Error: ${err.message}</div>`;
            }
        }
    }

    async deleteSeguimiento(id) {
        if (!confirm('¿Estás seguro de que quieres eliminar esta ruta de seguimiento?')) return;
        try {
            // Sin comprobar, un borrado fallido dejaba la ruta en disco mientras
            // la interfaz anunciaba "Ruta eliminada".
            await prigJson(await fetch(`/api/guided/${id}`, { method: 'DELETE' }));
            if (this.currentData && this.currentData.id === id) {
                this.currentData = null;
                if (this.canvasContent) {
                    this.canvasContent.innerHTML = '<div style="text-align: center; color: var(--text-muted); margin-top: 60px;"><i class="fa-solid fa-map-location-dot fa-3x" style="opacity: 0.5; margin-bottom: 15px;"></i><p>Ruta eliminada.</p></div>';
                }
                this.clearSVGConnectors();
                if (this.progressBar) this.progressBar.style.display = 'none';
            }
            this.fetchHistory();
        } catch (err) {
            console.error(err);
            alert("Error al eliminar");
        }
    }

    /** Selector de profundidad: sustituye a tener dos sistemas separados */
    initModoSelector() {
        const cont = document.getElementById('guiado-modo');
        if (!cont || cont.dataset.listo === '1') return;
        cont.dataset.listo = '1';

        cont.addEventListener('click', (e) => {
            const btn = e.target.closest('.modo-pill');
            if (!btn) return;
            this.modo = btn.dataset.modo;

            cont.querySelectorAll('.modo-pill').forEach(b => {
                const activo = b.dataset.modo === this.modo;
                b.classList.toggle('active', activo);
                if (b.dataset.modo === 'rapido') {
                    b.style.background = activo ? 'var(--accent-green)' : 'rgba(166,227,161,0.12)';
                    b.style.color = activo ? '#111' : 'var(--accent-green)';
                } else {
                    b.style.background = activo ? 'var(--accent-purple)' : 'rgba(203,166,247,0.12)';
                    b.style.color = activo ? '#111' : 'var(--accent-purple)';
                }
            });

            const ayuda = document.getElementById('guiado-modo-ayuda');
            if (ayuda) {
                ayuda.textContent = this.modo === 'profundo'
                    ? 'Tres agentes leen tu biblioteca, construyen el mapa de conceptos y generan cuadernos. Tarda varios minutos.'
                    : 'Un agente ordena los temas que escribas abajo.';
            }

            // En modo profundo los temas son opcionales: los deduce de la biblioteca
            const temas = document.getElementById('seguimiento-topics');
            if (temas) {
                temas.placeholder = this.modo === 'profundo'
                    ? 'Opcional en modo profundo: se deducen de tu biblioteca…'
                    : 'Pega aquí los temas...';
            }
        });
    }

    async cancelGeneration() {
        if (!this.isGenerating) return;
        console.log("🛑 Cancelando generación de ruta guiada...");
        this.isGenerating = false;

        if (this._timerInterval) {
            clearInterval(this._timerInterval);
            this._timerInterval = null;
        }

        if (this.abortController) {
            try {
                this.abortController.abort();
            } catch (e) {}
            this.abortController = null;
        }

        try {
            fetch('/api/guided/cancel', { method: 'POST' }).catch(() => {});
        } catch (e) {}

        if (this.btnCancel) this.btnCancel.style.display = 'none';
        if (this.btnGenerate) {
            this.btnGenerate.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Crear Ruta';
            this.btnGenerate.disabled = false;
        }

        if (this.canvasContent) {
            this.canvasContent.innerHTML = `
                <div style="max-width: 520px; margin: 40px auto; background: rgba(30, 30, 46, 0.95); border: 1px solid var(--border-color); border-radius: 12px; padding: 28px; text-align: center; box-shadow: 0 10px 30px rgba(0,0,0,0.5);">
                    <div style="margin-bottom: 14px;">
                        <i class="fa-solid fa-circle-pause fa-3x" style="color: var(--accent-yellow); opacity: 0.9;"></i>
                    </div>
                    <h3 style="margin: 0 0 8px 0; color: #fff; font-size: 16px;">Generación Cancelada</h3>
                    <p style="font-size: 13px; color: var(--text-muted); margin: 0 0 18px 0; line-height: 1.5;">
                        Has detenido la creación del plan. Se interrumpió el proceso en el modelo para liberar recursos.
                    </p>
                    <button class="tool-btn btn-primary" onclick="window.generarRutaGuiada();" style="padding: 7px 16px; font-weight: bold; font-size: 12px;">
                        <i class="fa-solid fa-rotate-right"></i> Volver a Intentar
                    </button>
                </div>
            `;
        }
    }

    async generateSeguimiento() {
        const goalEl = this.goalInput;
        const topicsEl = this.topicsInput;
        const goal = goalEl ? goalEl.value.trim() : "";
        const topics = topicsEl ? topicsEl.value.trim() : "";
        const modelEl = this.modelInput;
        const model = (modelEl && modelEl.value) 
            ? modelEl.value 
            : ((window.aiConfig && window.aiConfig.agent1_model) ? window.aiConfig.agent1_model : "qwen2.5-coder:7b");

        // Input validation with visual error feedback in UI
        let hasError = false;
        if (!goal) {
            if (goalEl) {
                goalEl.style.border = "2px solid var(--accent-red)";
            }
            hasError = true;
        } else if (goalEl) {
            goalEl.style.border = "1px solid var(--border-color)";
        }

        // En modo profundo los temas salen de la biblioteca, así que no son obligatorios
        if (!topics && this.modo !== 'profundo') {
            if (topicsEl) {
                topicsEl.style.border = "2px solid var(--accent-red)";
            }
            hasError = true;
        } else if (topicsEl) {
            topicsEl.style.border = "1px solid var(--border-color)";
        }

        if (hasError) {
            if (this.canvasContent) {
                this.canvasContent.innerHTML = `
                    <div style="max-width: 480px; margin: 40px auto; background: rgba(243,139,168,0.1); border: 1px solid var(--accent-red); border-radius: 10px; padding: 24px; text-align: center;">
                        <i class="fa-solid fa-triangle-exclamation fa-2x" style="color: var(--accent-red); margin-bottom: 10px;"></i>
                        <h4 style="margin: 0 0 8px 0; color: var(--accent-red);">Faltan campos obligatorios</h4>
                        <p style="font-size: 13px; color: var(--text-main); margin: 0; line-height: 1.5;">
                            Por favor escribe un <strong>Objetivo Principal</strong> (ej: <em>Aprender Python</em>) y pega tu <strong>Lista de Temas</strong> en los campos inferiores resaltados en rojo.
                        </p>
                    </div>
                `;
            }
            return;
        }

        this.isGenerating = true;
        this.abortController = new AbortController();

        const btn = this.btnGenerate;
        if (btn) {
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Generando...';
            btn.disabled = true;
        }
        if (this.btnCancel) {
            this.btnCancel.style.display = 'inline-flex';
        }
        
        this.clearSVGConnectors();
        if (this.progressBar) this.progressBar.style.display = 'none';

        // Definición de etapas
        const stages = this.modo === 'profundo' ? [
            { num: 1, title: "Biblioteca y Fuentes", desc: "Explorando biblioteca y analizando libros/código" },
            { num: 2, title: "Agente 1: Knowledge Architect", desc: "Diseñando mapa conceptual y dependencias" },
            { num: 3, title: "Agente 2: Practice Architect", desc: "Construyendo módulos y verificaciones prácticas" },
            { num: 4, title: "Agente 3: Notebook Manager", desc: "Generando cuadernos interactivos Jupyter" },
            { num: 5, title: "Finalización", desc: "Estructurando y guardando ruta pedagógica" }
        ] : [
            { num: 1, title: "Conexión", desc: "Iniciando conexión con modelo Ollama" },
            { num: 2, title: "Análisis de Temas", desc: "Analizando meta y clasificando temas pedagógicos" },
            { num: 3, title: "Razonamiento y Bloques", desc: "El modelo diseña la progresión y los hitos prácticos" },
            { num: 4, title: "Estructuración", desc: "Validando y guardando plan de aprendizaje" }
        ];

        let currentStageNum = 1;
        let currentPct = 10;
        let currentMessage = `Iniciando conexión con modelo Ollama (${model})...`;
        let reasoningText = "";
        let tokensReceived = 0;
        let elapsedSeconds = 0;

        const formatTime = (secs) => {
            const m = Math.floor(secs / 60).toString().padStart(2, '0');
            const s = (secs % 60).toString().padStart(2, '0');
            return `${m}:${s}`;
        };

        const renderLoadingCard = () => {
            if (!this.canvasContent || !this.isGenerating) return;

            const stagesHtml = stages.map(s => {
                let iconHtml = '';
                let itemStyle = 'padding: 6px 10px; border-radius: 6px; display: flex; align-items: center; justify-content: space-between; font-size: 11px; transition: all 0.2s;';
                
                if (s.num < currentStageNum) {
                    iconHtml = '<i class="fa-solid fa-circle-check" style="color: var(--accent-green);"></i>';
                    itemStyle += ' background: rgba(166,227,161,0.06); color: var(--text-main);';
                } else if (s.num === currentStageNum) {
                    iconHtml = '<i class="fa-solid fa-spinner fa-spin" style="color: var(--accent-yellow);"></i>';
                    itemStyle += ' background: rgba(249,226,175,0.12); color: #fff; font-weight: bold; border: 1px solid rgba(249,226,175,0.25);';
                } else {
                    iconHtml = '<i class="fa-regular fa-circle" style="color: var(--text-muted); opacity: 0.4;"></i>';
                    itemStyle += ' opacity: 0.55; color: var(--text-muted);';
                }

                return `
                    <div style="${itemStyle}">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            ${iconHtml}
                            <span><strong>Etapa ${s.num}:</strong> ${s.title}</span>
                        </div>
                        <span style="font-size: 10px; opacity: 0.8;">${s.desc}</span>
                    </div>
                `;
            }).join('');

            this.canvasContent.innerHTML = `
                <div style="max-width: 620px; margin: 25px auto; background: rgba(30, 30, 46, 0.95); border: 1px solid var(--border-color); border-radius: 12px; padding: 22px; box-shadow: 0 10px 30px rgba(0,0,0,0.5);">
                    <!-- Header -->
                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; border-bottom: 1px solid rgba(255,255,255,0.08); padding-bottom: 12px;">
                        <div style="display: flex; align-items: center; gap: 10px;">
                            <i class="fa-solid fa-brain fa-xl" style="color: var(--accent-blue);"></i>
                            <div>
                                <h4 style="margin: 0; color: #fff; font-size: 15px; font-weight: 700;">Creando Plan de Aprendizaje</h4>
                                <div style="font-size: 11px; color: var(--text-muted);">${goal ? `Objetivo: <em>${goal}</em>` : ''}</div>
                            </div>
                        </div>
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <span style="font-size: 11px; background: rgba(203,166,247,0.12); color: var(--accent-purple); border: 1px solid rgba(203,166,247,0.3); padding: 3px 8px; border-radius: 12px; display: inline-flex; align-items: center; gap: 5px;">
                                <i class="fa-solid fa-microchip"></i> ${model}
                            </span>
                            <span id="guiado-loading-timer" style="font-size: 12px; font-family: monospace; color: var(--accent-yellow); background: rgba(0,0,0,0.3); padding: 3px 8px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.06);">
                                ${formatTime(elapsedSeconds)}
                            </span>
                        </div>
                    </div>

                    <!-- Progress Bar -->
                    <div style="width: 100%; height: 8px; background: rgba(0,0,0,0.4); border-radius: 4px; overflow: hidden; margin-bottom: 8px; border: 1px solid rgba(255,255,255,0.08);">
                        <div id="guiado-progress-bar-fill" style="width: ${currentPct}%; height: 100%; background: linear-gradient(90deg, var(--accent-blue), var(--accent-purple), var(--accent-green)); transition: width 0.35s ease; border-radius: 4px;"></div>
                    </div>
                    <div style="display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 14px;">
                        <span id="guiado-stage-message" style="color: var(--accent-yellow); font-weight: 500;">
                            <i class="fa-solid fa-spinner fa-spin"></i> ${currentMessage}
                        </span>
                        <span id="guiado-progress-pct" style="font-weight: bold; color: #fff;">${currentPct}%</span>
                    </div>

                    <!-- Real Stages Stepper -->
                    <div id="guiado-stages-container" style="display: flex; flex-direction: column; gap: 6px; margin-bottom: 14px; background: rgba(0,0,0,0.2); padding: 8px 10px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.05);">
                        ${stagesHtml}
                    </div>

                    <!-- Reasoning / Thinking Box -->
                    <div style="margin-bottom: 16px; border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; overflow: hidden; background: rgba(0,0,0,0.3);">
                        <div style="padding: 6px 10px; background: rgba(255,255,255,0.03); display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid rgba(255,255,255,0.05);">
                            <span style="font-size: 11px; font-weight: 600; color: var(--accent-purple); display: flex; align-items: center; gap: 6px;">
                                <i class="fa-solid fa-lightbulb"></i> Razonamiento del Modelo (Thinking)
                            </span>
                            <span id="guiado-tokens-badge" style="font-size: 10px; color: var(--text-muted);">${tokensReceived > 0 ? `~${tokensReceived} tokens` : 'En espera'}</span>
                        </div>
                        <div id="guiado-thinking-content" style="max-height: 140px; overflow-y: auto; padding: 8px 10px; font-family: monospace; font-size: 11px; color: #bac2de; line-height: 1.4; text-align: left; white-space: pre-wrap; word-break: break-word;">
                            ${reasoningText ? reasoningText : `<span style="color: var(--text-muted); font-style: italic;"><i class="fa-solid fa-spinner fa-spin"></i> Esperando actividad de razonamiento del modelo...</span>`}
                        </div>
                    </div>

                    <!-- Actions: Cancel Button -->
                    <div style="display: flex; justify-content: center; gap: 10px;">
                        <button id="btn-cancel-generation-card" onclick="window.guiadoMgr.cancelGeneration();" class="tool-btn" style="background: rgba(243,139,168,0.15); color: var(--accent-red); border: 1px solid var(--accent-red); padding: 7px 18px; border-radius: 8px; font-weight: 600; font-size: 12px; cursor: pointer; display: inline-flex; align-items: center; gap: 6px; transition: all 0.2s;">
                            <i class="fa-solid fa-ban"></i> Cancelar Plan
                        </button>
                    </div>
                </div>
            `;
        };

        renderLoadingCard();

        this._timerInterval = setInterval(() => {
            elapsedSeconds++;
            const timerEl = document.getElementById('guiado-loading-timer');
            if (timerEl) timerEl.textContent = formatTime(elapsedSeconds);
        }, 1000);

        try {
            const reqData = {
                goal: goal,
                topics: topics,
                mode: this.modo,
                level: this.levelInput ? this.levelInput.value : "Intermedio",
                focus: this.focusInput ? this.focusInput.value : "Práctico",
                model: model
            };

            let response = await fetch('/api/guided/generate/stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(reqData),
                signal: this.abortController.signal
            });

            let finalData = null;

            if (!response.ok && response.status === 404) {
                // Fallback a endpoint no-stream si fuera necesario
                response = await fetch('/api/guided/generate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(reqData),
                    signal: this.abortController.signal
                });
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                finalData = await response.json();
            } else if (!response.ok) {
                let detail = `HTTP ${response.status}`;
                try {
                    const err = await response.clone().json();
                    detail = err.detail || err.error || detail;
                } catch (parseErr) {
                    const text = await response.text().catch(() => '');
                    if (text.trim()) detail = text.trim().slice(0, 300);
                }
                throw new Error(detail);
            } else {
                // Leer stream NDJSON en tiempo real
                const reader = response.body.getReader();
                const decoder = new TextDecoder("utf-8");
                let buffer = "";

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;

                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split("\n");
                    buffer = lines.pop(); // conservar resto incompleto

                    for (const line of lines) {
                        const trimmed = line.trim();
                        if (!trimmed) continue;
                        let event;
                        try {
                            event = JSON.parse(trimmed);
                        } catch (e) {
                            continue;
                        }

                        if (event.type === 'stage') {
                            if (event.stage_num) currentStageNum = event.stage_num;
                            if (event.pct !== undefined) currentPct = event.pct;
                            if (event.message) currentMessage = event.message;
                            renderLoadingCard();
                        } else if (event.type === 'thought') {
                            reasoningText += event.text;
                            tokensReceived += event.text.length > 4 ? Math.ceil(event.text.length / 4) : 1;
                            const thinkingEl = document.getElementById('guiado-thinking-content');
                            if (thinkingEl) {
                                thinkingEl.textContent = reasoningText;
                                thinkingEl.scrollTop = thinkingEl.scrollHeight;
                            }
                            const tokensBadge = document.getElementById('guiado-tokens-badge');
                            if (tokensBadge) {
                                tokensBadge.textContent = `~${tokensReceived} tokens`;
                            }
                        } else if (event.type === 'token') {
                            tokensReceived++;
                            const tokensBadge = document.getElementById('guiado-tokens-badge');
                            if (tokensBadge) {
                                tokensBadge.textContent = `~${tokensReceived} tokens`;
                            }
                            const thinkingEl = document.getElementById('guiado-thinking-content');
                            if (thinkingEl && !reasoningText) {
                                thinkingEl.innerHTML = `<span style="color: var(--accent-green);"><i class="fa-solid fa-gear fa-spin"></i> Generando bloques y validaciones (~${tokensReceived} fragmentos)...</span>`;
                            }
                        } else if (event.type === 'done') {
                            finalData = event.path;
                        } else if (event.type === 'error') {
                            throw new Error(event.message || "Error al generar la ruta");
                        }
                    }
                }
            }

            if (this._timerInterval) {
                clearInterval(this._timerInterval);
                this._timerInterval = null;
            }

            if (!finalData) {
                throw new Error("El modelo terminó sin devolver una estructura de plan válida.");
            }

            currentPct = 100;
            currentMessage = "¡Plan generado con éxito!";
            currentStageNum = stages.length;
            renderLoadingCard();

            setTimeout(() => {
                this.isGenerating = false;
                this.abortController = null;
                if (this.btnCancel) this.btnCancel.style.display = 'none';
                this.currentData = finalData;
                this.completedBlocks.clear();
                this.renderCanvas(finalData);
                this.updateProgressUI();
                if (this.progressBar) this.progressBar.style.display = 'flex';
                this.fetchHistory();
            }, 350);

        } catch (err) {
            if (this._timerInterval) {
                clearInterval(this._timerInterval);
                this._timerInterval = null;
            }

            // Si fue abortado por el usuario, cancelGeneration ya limpió y mostró el aviso
            if (err.name === 'AbortError' || !this.isGenerating) {
                console.log("Generación abortada por el usuario.");
                return;
            }

            this.isGenerating = false;
            this.abortController = null;
            if (this.btnCancel) this.btnCancel.style.display = 'none';

            console.error("Error en generateSeguimiento:", err);
            if (this.canvasContent) {
                this.canvasContent.innerHTML = `
                    <div style="max-width: 520px; margin: 40px auto; color: var(--accent-red); padding: 20px; border: 1px solid var(--accent-red); border-radius: 10px; background: rgba(243,139,168,0.1); text-align: center;">
                        <i class="fa-solid fa-circle-exclamation fa-2x" style="margin-bottom: 10px;"></i>
                        <h4 style="margin: 0 0 8px 0;">Error al Generar la Ruta</h4>
                        <p style="font-size: 12px; margin-bottom: 15px; color: var(--text-main);">${err.message}</p>
                        <button class="tool-btn btn-primary" onclick="window.generarRutaGuiada();">
                            <i class="fa-solid fa-rotate-right"></i> Reintentar
                        </button>
                    </div>
                `;
            }
        } finally {
            if (!this.isGenerating) {
                if (this.btnCancel) this.btnCancel.style.display = 'none';
                if (btn) {
                    btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Crear Ruta';
                    btn.disabled = false;
                }
            }
        }
    }

    renderCanvas(data) {
        if (!this.canvasContent) return;
        if (!data.blocks || data.blocks.length === 0) {
            this.canvasContent.innerHTML = `<div style="padding: 10px; color: var(--accent-yellow); text-align: center;">No se generaron bloques. Verifica la lista de temas.</div>`;
            return;
        }

        let html = `
            <div style="max-width: 650px; margin: 0 auto; display: flex; flex-direction: column; gap: 30px; padding-bottom: 50px;">
                <!-- Rationale Box & Export Jupyter Notebook Button -->
                <div style="background: rgba(137,180,250,0.1); border: 1px dashed var(--accent-blue); padding: 16px; border-radius: 8px; text-align: center; display: flex; flex-direction: column; align-items: center; gap: 10px;">
                    <h3 style="margin:0; color: var(--accent-blue); font-size: 16px;"><i class="fa-solid fa-bullseye"></i> Ruta hacia: ${data.goal}</h3>
                    <div style="font-size: 13px; color: var(--text-main); font-style: italic;">"${data.rationale || 'Ruta generada para maximizar el aprendizaje progresivo.'}"</div>
                    <button class="tool-btn" onclick="window.guiadoMgr.exportJupyterNotebook()" style="background: rgba(249,226,175,0.15); color: var(--accent-yellow); border: 1px solid var(--accent-yellow); font-weight: bold; font-size: 12px; padding: 6px 14px; border-radius: 6px; cursor: pointer; transition: all 0.2s;">
                        <i class="fa-solid fa-book"></i> 📓 Exportar como Cuaderno Jupyter (.ipynb)
                    </button>
                </div>
        `;

        data.blocks.forEach((block, index) => {
            let typeColor = 'var(--text-muted)';
            let icon = 'fa-book';
            
            if (block.type === 'theory') { typeColor = 'var(--accent-blue)'; icon = 'fa-brain'; }
            else if (block.type === 'practice') { typeColor = 'var(--accent-green)'; icon = 'fa-laptop-code'; }
            else if (block.type === 'project') { typeColor = 'var(--accent-yellow)'; icon = 'fa-rocket'; }
            else if (block.type === 'mixed') { typeColor = 'var(--accent-purple)'; icon = 'fa-layer-group'; }

            const id = block.block_id || `blk_${index}`;
            const isCompleted = this.completedBlocks.has(id);
            const statusClass = isCompleted ? 'border: 2px solid var(--accent-green); background: rgba(166,227,161,0.05);' : 'border: 1px solid var(--border-color); background: var(--bg-panel);';

            html += `
                <div id="${id}" style="${statusClass} border-radius: 10px; padding: 18px; position: relative; transition: all 0.3s ease; box-shadow: 0 4px 15px rgba(0,0,0,0.2);">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                        <span style="background: rgba(255,255,255,0.05); padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; color: ${typeColor}; display: flex; align-items: center; gap: 5px;">
                            <i class="fa-solid ${icon}"></i> ${block.type.toUpperCase()}
                        </span>
                        <span style="font-size: 11px; color: var(--text-muted);"><i class="fa-regular fa-clock"></i> ${block.estimated_time || '1 hora'}</span>
                    </div>

                    <h4 style="margin: 0 0 8px 0; font-size: 15px; color: #fff; display: flex; align-items: center; gap: 8px;">
                        <span style="background: var(--accent-blue); color: #111; width: 22px; height: 22px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-size: 11px; font-weight: bold;">${index + 1}</span>
                        ${block.title}
                    </h4>

                    <p style="font-size: 12px; color: var(--text-main); margin: 0 0 12px 0; line-height: 1.5;">${block.description}</p>

                    <!-- Objective & Validation -->
                    <div style="display: flex; flex-direction: column; gap: 6px; background: rgba(0,0,0,0.2); padding: 10px; border-radius: 6px; margin-bottom: 12px; font-size: 11px;">
                        <div style="color: var(--accent-yellow);">
                            <strong>🎯 Objetivo:</strong> ${block.learning_objective || 'Comprender conceptos clave'}
                        </div>
                        <div style="color: var(--accent-green);">
                            <strong>✅ Verificación:</strong> ${block.validation_check || 'Completar práctica sugerida'}
                        </div>
                    </div>

                    <!-- Topics Tags -->
                    <div style="display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 14px;">
                        ${(block.topics || []).map(t => `<span style="background: rgba(137,180,250,0.1); color: var(--accent-blue); padding: 2px 6px; border-radius: 4px; font-size: 10px;">#${t}</span>`).join('')}
                    </div>

                    <!-- Actions Bar -->
                    <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 12px;">
                        <button id="btn-done-${id}" class="tool-btn" onclick="window.guiadoMgr.toggleCompletion('${id}')" style="padding: 6px; border-radius: 6px; font-weight: bold; font-size: 10px; background: ${isCompleted ? 'var(--accent-green)' : 'rgba(255,255,255,0.05)'}; color: ${isCompleted ? '#111' : '#fff'}; border: 1px solid var(--border-color); transition: all 0.2s;">
                            <i class="fa-solid ${isCompleted ? 'fa-circle-check' : 'fa-circle'}"></i> ${isCompleted ? 'Hecho' : 'Completar'}
                        </button>
                        <button class="tool-btn" onclick="window.guiadoMgr.explainBlock('${id}')" style="padding: 6px; border-radius: 6px; font-weight: bold; font-size: 10px; background: rgba(137,180,250,0.1); color: var(--accent-blue); border: 1px solid var(--accent-blue); transition: all 0.2s;">
                            <i class="fa-solid fa-chalkboard-user"></i> Clase Tutor
                        </button>
                        <button class="tool-btn" onclick="window.guiadoMgr.startChallenge('${id}')" style="padding: 6px; border-radius: 6px; font-weight: bold; font-size: 10px; background: rgba(166,227,161,0.1); color: var(--accent-green); border: 1px solid var(--accent-green); transition: all 0.2s;">
                            <i class="fa-solid fa-chess-knight"></i> Desafío
                        </button>
                        <button class="tool-btn" onclick="window.guiadoMgr.startQuiz('${id}')" style="padding: 6px; border-radius: 6px; font-weight: bold; font-size: 10px; background: rgba(249,226,175,0.1); color: var(--accent-yellow); border: 1px solid var(--accent-yellow); transition: all 0.2s;">
                            <i class="fa-solid fa-vial"></i> Quiz IA
                        </button>
                    </div>
                </div>
            `;
        });

        html += `</div>`;
        this.canvasContent.innerHTML = html;

        setTimeout(() => this.drawConnectors(), 100);
    }

    toggleCompletion(blockId) {
        if (!this.currentData) return;
        
        if (this.completedBlocks.has(blockId)) {
            this.completedBlocks.delete(blockId);
        } else {
            this.completedBlocks.add(blockId);
        }

        const blockEl = document.getElementById(blockId);
        const btnDone = document.getElementById(`btn-done-${blockId}`);
        const isCompleted = this.completedBlocks.has(blockId);

        if (blockEl) {
            blockEl.style.border = isCompleted ? '2px solid var(--accent-green)' : '1px solid var(--border-color)';
            blockEl.style.background = isCompleted ? 'rgba(166,227,161,0.05)' : 'var(--bg-panel)';
        }

        if (btnDone) {
            btnDone.style.background = isCompleted ? 'var(--accent-green)' : 'rgba(255,255,255,0.05)';
            btnDone.style.color = isCompleted ? '#111' : '#fff';
            btnDone.innerHTML = `<i class="fa-solid ${isCompleted ? 'fa-circle-check' : 'fa-circle'}"></i> ${isCompleted ? 'Completado' : 'Marcar Hecho'}`;
        }

        this.updateProgressUI();
        this.saveProgressBackend();
        this.drawConnectors();
    }

    async saveProgressBackend() {
        if (!this.currentData || !this.currentData.id) return;
        try {
            await prigJson(await fetch(`/api/guided/${this.currentData.id}/progress`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ completed_blocks: Array.from(this.completedBlocks) })
            }));
            this.fetchHistory();
        } catch (e) {
            console.error("Error al guardar progreso:", e);
            if (window.terminalMgr) {
                window.terminalMgr.appendLine(`[No se pudo guardar el progreso del seguimiento: ${e.message}]`, 'stderr');
            }
        }
    }

    updateProgressUI() {
        if (!this.currentData || !this.currentData.blocks || !this.progressPct || !this.progressFill) return;
        const total = this.currentData.blocks.length;
        if (total === 0) return;

        const done = this.completedBlocks.size;
        const pct = Math.round((done / total) * 100);
        
        this.progressPct.innerText = `${pct}% Completado (${done}/${total})`;
        this.progressFill.style.width = `${pct}%`;
        
        if (pct === 100) {
            this.progressFill.style.boxShadow = '0 0 10px var(--accent-green)';
        } else {
            this.progressFill.style.boxShadow = 'none';
        }
    }

    clearSVGConnectors() {
        if (!this.svgOverlay) return;
        const paths = this.svgOverlay.querySelectorAll('path:not([d="M 0 0 L 10 5 L 0 10 z"])');
        paths.forEach(p => p.remove());
    }

    drawConnectors() {
        if (!this.currentData || !this.currentData.blocks) return;
        this.clearSVGConnectors();
        
        const blocks = this.currentData.blocks;
        for (let i = 0; i < blocks.length - 1; i++) {
            const currentId = blocks[i].block_id;
            const nextId = blocks[i+1].block_id;
            
            const srcEl = document.getElementById(currentId);
            const tgtEl = document.getElementById(nextId);
            
            if (srcEl && tgtEl) {
                const isCompleted = this.completedBlocks.has(currentId);
                const color = isCompleted ? 'var(--accent-green)' : 'var(--accent-blue)';
                const marker = isCompleted ? 'arrow-green' : 'arrow-blue-seg';
                this.drawSVGConnectorMath(srcEl, tgtEl, color, marker);
            }
        }
    }

    async exportJupyterNotebook() {
        if (!this.currentData || !this.currentData.id) return;
        try {
            const res = await fetch(`/api/guided/${this.currentData.id}/generate-notebook`, { method: 'POST' });
            if (!res.ok) throw new Error(await prigErrorDetail(res));
            const data = await res.json();
            alert(`📓 ${data.message}\nArchivo guardado en el workspace.`);
            if (window.fileTreeMgr) window.fileTreeMgr.refreshTree();
        } catch (err) {
            alert(`⚠️ Error: ${err.message}`);
        }
    }

    speakText(text) {
        if (!('speechSynthesis' in window)) return alert("Tu navegador no soporta TTS por voz.");
        window.speechSynthesis.cancel();
        const clean = text.replace(/```[\s\S]*?```/g, " Bloque de código omiso. ").replace(/[#*`_~]/g, "");
        const utterance = new SpeechSynthesisUtterance(clean);
        utterance.lang = "es-ES";
        utterance.rate = 1.0;
        window.speechSynthesis.speak(utterance);
    }

    stopVoice() {
        if ('speechSynthesis' in window) window.speechSynthesis.cancel();
    }

    renderMermaidDiagrams(container) {
        if (typeof mermaid === 'undefined' || !container) return;
        const mermaidBlocks = container.querySelectorAll('pre code.language-mermaid, pre.mermaid');
        mermaidBlocks.forEach((block, idx) => {
            const code = block.textContent;
            const parent = block.tagName.toLowerCase() === 'code' ? block.parentNode : block;
            const div = document.createElement('div');
            div.className = 'mermaid-rendered';
            div.style.cssText = 'background: rgba(0,0,0,0.3); padding: 12px; border-radius: 8px; margin: 12px 0; text-align: center; border: 1px solid var(--border-color);';
            div.id = `mermaid-seg-${Date.now()}-${idx}`;
            parent.parentNode.replaceChild(div, parent);
            try {
                mermaid.render(div.id + '-svg', code).then(({ svg }) => { div.innerHTML = svg; }).catch(e => {
                    div.innerHTML = `<pre style="color:var(--accent-red); font-size:11px;">[Diagrama Mermaid: ${code}]</pre>`;
                });
            } catch (e) {}
        });
    }

    async explainBlock(blockId) {
        if (!this.currentData || !this.currentData.blocks) return;
        
        const block = this.currentData.blocks.find(b => b.block_id === blockId);
        if (!block) return;

        const tutorContent = document.getElementById('seguimiento-tutor-content');
        if (!tutorContent) return;

        tutorContent.innerHTML = `<div style="text-align: center; color: var(--accent-blue); margin-top: 40px;"><i class="fa-solid fa-spinner fa-spin fa-2x"></i><p style="margin-top: 10px;">El Tutor está preparando la clase para <strong>${block.title}</strong>...</p></div>`;

        try {
            const reqData = {
                goal: this.currentData.goal,
                block: block,
                model: (this.modelInput && this.modelInput.value) ? this.modelInput.value : ((window.aiConfig && window.aiConfig.agent1_model) ? window.aiConfig.agent1_model : "qwen2.5-coder:7b")
            };

            const response = await fetch('/api/guided/explain', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(reqData)
            });

            if (!response.ok) throw new Error('Error al solicitar explicación');

            const reader = response.body.getReader();
            const decoder = new TextDecoder("utf-8");
            let markdownText = "";

            tutorContent.innerHTML = `
                <div style="display: flex; gap: 8px; margin-bottom: 12px; border-bottom: 1px solid var(--border-color); padding-bottom: 8px;">
                    <button class="tool-btn" onclick="window.guiadoMgr.speakText(document.getElementById('seguimiento-tutor-body').innerText)" style="background: rgba(203,166,247,0.15); color: var(--accent-purple); border: 1px solid var(--accent-purple); font-size: 11px;">
                        <i class="fa-solid fa-volume-high"></i> Escuchar Clase (Voz TTS)
                    </button>
                    <button class="tool-btn" onclick="window.guiadoMgr.stopVoice()" style="background: rgba(243,139,168,0.15); color: var(--accent-red); border: 1px solid var(--accent-red); font-size: 11px;">
                        <i class="fa-solid fa-stop"></i> Detener Voz
                    </button>
                </div>
                <div id="seguimiento-tutor-body" class="markdown-body" style="font-size: 13px;"></div>
            `;
            const mdContainer = tutorContent.querySelector('#seguimiento-tutor-body');

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                
                markdownText += decoder.decode(value, { stream: true });
                
                if (window.marked && window.marked.parse) {
                    mdContainer.innerHTML = window.marked.parse(markdownText);
                } else {
                    mdContainer.innerHTML = `<pre style="white-space: pre-wrap; font-family: inherit;">${markdownText}</pre>`;
                }
                tutorContent.scrollTop = tutorContent.scrollHeight;
            }

            this.renderMermaidDiagrams(mdContainer);

        } catch (err) {
            console.error(err);
            tutorContent.innerHTML = `<div style="color: var(--accent-red); padding: 10px;">Error: ${err.message}</div>`;
        }
    }

    /** El desafío del bloque se trabaja en la sección Desafíos: razonar, plan, páginas y pruebas */
    startChallenge(blockId) {
        if (!this.currentData || !window.Desafios) return;
        window.Desafios.abrir({ rutaId: this.currentData.id, bloqueId: blockId });
    }

    async startQuiz(blockId) {
        if (!this.currentData || !this.currentData.blocks) return;
        
        const block = this.currentData.blocks.find(b => b.block_id === blockId);
        if (!block) return;

        const tutorContent = document.getElementById('seguimiento-tutor-content');
        if (!tutorContent) return;

        tutorContent.innerHTML = `<div style="text-align: center; color: var(--accent-yellow); margin-top: 40px;"><i class="fa-solid fa-spinner fa-spin fa-2x"></i><p style="margin-top: 10px;">Generando Quiz de autoevaluación para <strong>${block.title}</strong>...</p></div>`;

        try {
            const res = await fetch('/api/guided/quiz', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    goal: this.currentData.goal,
                    block: block,
                    model: (this.modelInput && this.modelInput.value) ? this.modelInput.value : ((window.aiConfig && window.aiConfig.agent1_model) ? window.aiConfig.agent1_model : "qwen2.5-coder:7b")
                })
            });

            if (!res.ok) throw new Error(await prigErrorDetail(res));
            const quizData = await res.json();
            this.renderQuizUI(blockId, quizData);
        } catch (err) {
            console.error(err);
            tutorContent.innerHTML = `<div style="color: var(--accent-red); padding: 10px;">Error: ${err.message}</div>`;
        }
    }

    renderQuizUI(blockId, quiz) {
        const tutorContent = document.getElementById('seguimiento-tutor-content');
        if (!tutorContent) return;

        if (!quiz.questions || quiz.questions.length === 0) {
            tutorContent.innerHTML = '<div style="color: var(--accent-red); padding: 10px;">No se pudo generar el quiz.</div>';
            return;
        }

        let html = `
            <div style="padding: 10px; display: flex; flex-direction: column; gap: 20px;">
                <div style="border-bottom: 1px solid var(--border-color); padding-bottom: 10px;">
                    <h3 style="margin: 0 0 5px 0; color: var(--accent-yellow); font-size: 15px;"><i class="fa-solid fa-vial"></i> Quiz de Autoevaluación</h3>
                    <div style="font-size: 12px; color: var(--text-muted);">${quiz.block_title || 'Bloque'}</div>
                </div>
        `;

        quiz.questions.forEach((q, qIndex) => {
            html += `
                <div style="background: rgba(255,255,255,0.03); border: 1px solid var(--border-color); border-radius: 8px; padding: 14px;">
                    <strong style="color: #fff; font-size: 13px; display: block; margin-bottom: 10px;">${qIndex + 1}. ${q.question}</strong>
                    <div style="display: flex; flex-direction: column; gap: 6px;">
                        ${q.options.map((opt, oIndex) => `
                            <button class="quiz-opt-btn-${qIndex}" onclick="window.guiadoMgr.checkAnswer(${qIndex}, ${oIndex}, ${q.correct_index}, '${q.explanation.replace(/'/g, "\\'")}', '${blockId}')" style="text-align: left; padding: 8px 12px; border-radius: 6px; background: rgba(255,255,255,0.05); border: 1px solid var(--border-color); color: var(--text-main); cursor: pointer; font-size: 12px; transition: all 0.2s;">
                                ${opt}
                            </button>
                        `).join('')}
                    </div>
                    <div id="quiz-exp-${qIndex}" style="display: none; margin-top: 10px; padding: 10px; border-radius: 6px; font-size: 11px; line-height: 1.4;"></div>
                </div>
            `;
        });

        html += `</div>`;
        tutorContent.innerHTML = html;
    }

    checkAnswer(qIndex, selectedIndex, correctIndex, explanation, blockId) {
        const btns = document.querySelectorAll(`.quiz-opt-btn-${qIndex}`);
        btns.forEach((btn, idx) => {
            btn.disabled = true;
            btn.style.cursor = 'default';
            if (idx === correctIndex) {
                btn.style.background = 'rgba(166,227,161,0.2)';
                btn.style.borderColor = 'var(--accent-green)';
                btn.style.color = 'var(--accent-green)';
            } else if (idx === selectedIndex) {
                btn.style.background = 'rgba(243,139,168,0.2)';
                btn.style.borderColor = 'var(--accent-red)';
                btn.style.color = 'var(--accent-red)';
            }
        });

        const expEl = document.getElementById(`quiz-exp-${qIndex}`);
        if (expEl) {
            expEl.style.display = 'block';
            if (selectedIndex === correctIndex) {
                expEl.style.background = 'rgba(166,227,161,0.1)';
                expEl.style.color = 'var(--accent-green)';
                expEl.innerHTML = `<strong>¡Correcto!</strong> ${explanation}`;
            } else {
                expEl.style.background = 'rgba(243,139,168,0.1)';
                expEl.style.color = 'var(--accent-red)';
                expEl.innerHTML = `<strong>Incorrecto.</strong> ${explanation}`;
            }
        }
    }

    exportMarkdown() {
        if (!this.currentData) {
            alert("No hay ningún seguimiento activo para exportar.");
            return;
        }

        let md = `# 🗺️ Plan de Seguimiento: ${this.currentData.goal}\n\n`;
        md += `**Temas Originales:** ${this.currentData.topics_raw || 'N/A'}\n`;
        md += `**Fecha de Creación:** ${new Date(this.currentData.created_at || Date.now()).toLocaleDateString()}\n\n`;
        md += `## 💡 Razonamiento Pedagógico\n${this.currentData.rationale || ''}\n\n`;
        md += `---\n\n## 📌 Bloques de Aprendizaje\n\n`;

        (this.currentData.blocks || []).forEach((b, i) => {
            const isDone = this.completedBlocks.has(b.block_id) ? '[x]' : '[ ]';
            md += `### ${i + 1}. ${b.title} ${isDone}\n`;
            md += `- **Descripción:** ${b.description}\n`;
            md += `- **Objetivo de Aprendizaje:** ${b.learning_objective || 'N/A'}\n`;
            md += `- **Validación Práctica:** ${b.validation_check || 'N/A'}\n`;
            md += `- **Tiempo Estimado:** ${b.estimated_time || 'N/A'}\n`;
            md += `- **Temas Clave:** ${(b.topics || []).join(', ')}\n\n`;
        });

        const blob = new Blob([md], { type: 'text/markdown' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `seguimiento_${(this.currentData.goal || 'plan').replace(/[^a-z0-9]/gi, '_').toLowerCase()}.md`;
        a.click();
        URL.revokeObjectURL(url);
    }

    drawSVGConnectorMath(fromEl, toEl, color, markerId) {
        if (!this.svgOverlay || !this.canvasContainer) return;

        const cRect = this.canvasContainer.getBoundingClientRect();
        const fRect = fromEl.getBoundingClientRect();
        const tRect = toEl.getBoundingClientRect();

        const x1 = fRect.left + fRect.width / 2 - cRect.left + this.canvasContainer.scrollLeft;
        const y1 = fRect.bottom - cRect.top + this.canvasContainer.scrollTop;

        const x2 = tRect.left + tRect.width / 2 - cRect.left + this.canvasContainer.scrollLeft;
        const y2 = tRect.top - cRect.top + this.canvasContainer.scrollTop;

        const deltaY = Math.max(30, Math.abs(y2 - y1) / 2);
        const pathData = `M ${x1} ${y1} C ${x1} ${y1 + deltaY}, ${x2} ${y2 - deltaY}, ${x2} ${y2}`;

        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', pathData);
        path.setAttribute('stroke', color);
        path.setAttribute('stroke-width', '3');
        path.setAttribute('fill', 'none');
        path.setAttribute('marker-end', `url(#${markerId})`);
        path.setAttribute('opacity', '0.7');
        path.setAttribute('stroke-dasharray', color === 'var(--accent-green)' ? 'none' : '5,5');

        this.svgOverlay.appendChild(path);
    }
}

// Global Helpers for HTML Onclick Binding
window.generarRutaGuiada = function() {
    if (!window.guiadoMgr) {
        window.guiadoMgr = new AprendizajeGuiadoManager();
    }
    window.guiadoMgr.generateSeguimiento();
};

window.abrirAprendizajeGuiado = function() {
    if (!window.guiadoMgr) {
        window.guiadoMgr = new AprendizajeGuiadoManager();
    }
    window.guiadoMgr.openModal();
};

function initSeguimientoModule() {
    if (!window.guiadoMgr) {
        window.guiadoMgr = new AprendizajeGuiadoManager();
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSeguimientoModule);
} else {
    initSeguimientoModule();
}
