class AIChatManager {
    constructor() {
        this.messagesContainer = document.getElementById('ai-chat-messages');
        this.inputEl = document.getElementById('ai-chat-input');
        this.sendBtn = document.getElementById('btn-send-ai');
        this.modelSelect = document.getElementById('model-select');
        this.statusDot = document.getElementById('ai-status-dot');
        this.statusText = document.getElementById('ai-status-text');

        this.installedModels = [];
        this.capacidades = {};
        this.previousSelectedModel = this.modelSelect ? this.modelSelect.value : "qwen2.5-coder:7b";

        // Archivos enganchados para contexto y edición asistida por IA (Gancho)
        this.hookedFiles = new Set();
        this.pendingHookedFiles = new Set();
        this.treeData = [];

        this.initEvents();
        this.checkStatus().then(() => this.cargarCapacidades());
    }

    initEvents() {
        this.sendBtn.onclick = () => this.sendMessage();
        this.inputEl.onkeydown = (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        };

        if (this.modelSelect) {
            this.modelSelect.onchange = () => { this.handleModelChange(); this.pintarOpcionesModelo(); };
        }
        const herr = document.getElementById('chk-herramientas');
        if (herr) herr.onchange = () => this.pintarOpcionesModelo();
        window.addEventListener('prig:models-updated', () => this.cargarCapacidades());

        // Controles de Gancho (archivos y carpetas para el chat)
        const btnGancho = document.getElementById('btn-chat-gancho');
        if (btnGancho) btnGancho.onclick = () => this.openGanchoModal();

        const btnCerrarGancho = document.getElementById('btn-cerrar-modal-gancho');
        if (btnCerrarGancho) btnCerrarGancho.onclick = () => this.closeGanchoModal();

        const btnCancelarGancho = document.getElementById('btn-gancho-cancelar');
        if (btnCancelarGancho) btnCancelarGancho.onclick = () => this.closeGanchoModal();

        const btnConfirmarGancho = document.getElementById('btn-gancho-confirmar');
        if (btnConfirmarGancho) btnConfirmarGancho.onclick = () => this.confirmGanchoSelection();

        const btnGanchoActivo = document.getElementById('btn-gancho-activo');
        if (btnGanchoActivo) btnGanchoActivo.onclick = () => this.ganchoSelectActiveFile();

        const btnGanchoTodos = document.getElementById('btn-gancho-todos');
        if (btnGanchoTodos) btnGanchoTodos.onclick = () => this.ganchoSelectAll();

        const btnGanchoLimpiar = document.getElementById('btn-gancho-limpiar');
        if (btnGanchoLimpiar) btnGanchoLimpiar.onclick = () => this.ganchoClearAll();

        const searchGancho = document.getElementById('gancho-search-input');
        if (searchGancho) {
            searchGancho.oninput = () => this.filterGanchoTree(searchGancho.value.trim().toLowerCase());
        }

        // Modal de descarga de modelos
        const btnCancel = document.getElementById('btn-cancel-download');
        const btnCloseModal = document.getElementById('btn-close-download-modal');
        if (btnCancel) btnCancel.onclick = () => this.closeDownloadModal(false);
        if (btnCloseModal) btnCloseModal.onclick = () => this.closeDownloadModal(false);

        const btnConfirm = document.getElementById('btn-confirm-download');
        if (btnConfirm) btnConfirm.onclick = () => this.startModelDownload();
    }

    handleModelChange() {
        const selectedModel = this.modelSelect.value;
        if (this.installedModels.length > 0 && !this.installedModels.includes(selectedModel)) {
            this.openDownloadModal(selectedModel);
        } else {
            this.liberarModelo(this.previousSelectedModel, selectedModel);
            this.previousSelectedModel = selectedModel;
        }
    }

    /**
     * Al cambiar de modelo, el anterior se saca de la memoria de la GPU.
     *
     * Ollama lo deja cargado el tiempo de keep_alive (30 min por defecto aquí). Si los
     * dos caben, conviven; si no, el nuevo arranca repartido entre GPU y CPU, más lento
     * y calentando las dos. Descargarlo al cambiar evita ambas cosas.
     */
    liberarModelo(anterior, nuevo) {
        if (!anterior || anterior === nuevo || anterior.startsWith('gemini:')) return;
        fetch('/api/modelos/descargar', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                          body: JSON.stringify({ modelo: anterior }) }).catch(() => {});
    }

    openDownloadModal(modelName) {
        const modal = document.getElementById('modal-download-model');
        if (!modal) return;

        document.getElementById('dl-model-title').textContent = modelName;
        const infoEl = document.getElementById('dl-model-info');
        const progressContainer = document.getElementById('dl-progress-container');
        const btnConfirm = document.getElementById('btn-confirm-download');
        
        progressContainer.style.display = 'none';
        btnConfirm.disabled = false;
        btnConfirm.innerHTML = '<i class="fa-solid fa-check"></i> Aceptar y Descargar';

        let info = `<strong>Modelo:</strong> ${modelName}<br><strong>Descripción:</strong> Modelo especializado para ejecución local en Ollama.<br><strong>Requisito estimado:</strong> 4 a 16 GB RAM.`;

        if (modelName.includes('qwen3.8')) {
            info = `<strong>Modelo:</strong> ${modelName} (Qwen 3.8 Dense Multimodal)<br><strong>Descripción:</strong> Modelo multimodal avanzado con ventana de contexto de 262k, comprensión de imágenes/video y control de razonamiento paso a paso.<br><strong>Tamaño aproximado:</strong> 16 GB.<br><strong>Memoria recomendada:</strong> 18 GB RAM (Ideal para tus 64GB de RAM).`;
        } else if (modelName.includes('27b')) {
            info = `<strong>Modelo:</strong> ${modelName} (27 Billones de parámetros)<br><strong>Descripción:</strong> Modelo de alta precisión para comprensión de código extenso y análisis algorítmico.<br><strong>Tamaño aproximado:</strong> 16 GB.<br><strong>Memoria recomendada:</strong> 18 GB de RAM (perfecto para tus 64GB).`;
        } else if (modelName.includes('32b')) {
            info = `<strong>Modelo:</strong> ${modelName} (32 Billones de parámetros)<br><strong>Descripción:</strong> Modelo avanzado para razonamiento profundo y arquitectura de software compleja.<br><strong>Tamaño aproximado:</strong> 19 GB.<br><strong>Memoria recomendada:</strong> 20 GB de RAM.`;
        } else if (modelName.includes('math')) {
            info = `<strong>Modelo:</strong> ${modelName} (Especializado en Matemáticas)<br><strong>Descripción:</strong> Diseñado para resolver cálculo, demostraciones y desgloses de algoritmos ML.<br><strong>Tamaño aproximado:</strong> 4.7 GB.<br><strong>Memoria recomendada:</strong> 6 GB RAM / VRAM.`;
        } else if (modelName.includes('coder:7b') || modelName.includes('7b')) {
            info = `<strong>Modelo:</strong> ${modelName} (7 Billones de parámetros)<br><strong>Descripción:</strong> Modelo recomendado para autocompletado y tutoría de programación en tiempo real.<br><strong>Tamaño aproximado:</strong> 4.7 GB.<br><strong>Memoria recomendada:</strong> 6 GB RAM / VRAM.`;
        } else if (modelName.includes('deepseek')) {
            info = `<strong>Modelo:</strong> ${modelName} (Razonamiento Lógico)<br><strong>Descripción:</strong> Modelo de pensamiento estructurado paso a paso.<br><strong>Tamaño aproximado:</strong> 4.9 GB.`;
        }

        infoEl.innerHTML = info;
        modal.style.display = 'flex';
        this.pendingDownloadModel = modelName;
    }

    closeDownloadModal(success = false) {
        const modal = document.getElementById('modal-download-model');
        if (modal) modal.style.display = 'none';

        if (!success) {
            // Revertir selección al modelo previo instalado
            if (this.previousSelectedModel) {
                this.modelSelect.value = this.previousSelectedModel;
            }
        }
    }

    async startModelDownload() {
        const rawModel = this.pendingDownloadModel || this.modelSelect.value;
        const cleanTag = (rawModel || '').split(/[\s(]/)[0].trim();
        const aliasMap = {
            'olmoe:1b-7b': 'hf.co/bartowski/OLMoE-1B-7B-0924-Instruct-GGUF:Q4_K_M',
            'r1-distill-qwen-math:1.5b': 'deepseek-r1:1.5b',
            'deepseek-r1-0528-qwen3:8b': 'deepseek-r1:8b',
            'qwen3-coder-r1:slerp': 'qwen3-coder:30b',
            'dolphin-qwen3-r1:abliterated': 'dolphin3:8b',
            'dolphin-r1-qwen:14b': 'dolphin3:8b',
            'qwen2.5-moe:2.7b': 'hf.co/RichardErkhov/Qwen_-_Qwen1.5-MoE-A2.7B-Chat-gguf:Q4_K_M',
            'qwen3-30b-a3b:r1-distill': 'qwen3:30b-a3b',
            'qwen3.6-35b-a3b:latest': 'qwen3.6:35b-a3b',
            'phi3.5-moe:latest': 'hf.co/bartowski/Phi-3.5-MoE-instruct-GGUF:Q4_K_M',
            // Nombres antiguos que no existían en ningún registro (daban 404): se
            // redirigen a su equivalente real verificado
            'qwen3-30b-a3b': 'qwen3:30b-a3b',
            'qwen3.6-35b-a3b': 'qwen3.6:35b-a3b',
            'deepseek-coder-v2-lite': 'deepseek-coder-v2:16b',
            'deepseek-coder-v2:lite': 'deepseek-coder-v2:16b'
        };
        const modelName = aliasMap[cleanTag] || cleanTag;

        const progressContainer = document.getElementById('dl-progress-container');
        const progressBar = document.getElementById('dl-progress-bar');
        const progressLabel = document.getElementById('dl-status-label');
        const progressPct = document.getElementById('dl-status-percentage');
        const btnConfirm = document.getElementById('btn-confirm-download');

        progressContainer.style.display = 'block';
        btnConfirm.disabled = true;
        btnConfirm.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Descargando...';
        progressLabel.style.color = 'var(--text-muted)';

        try {
            const res = await fetch('/api/ai/pull', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ model: modelName })
            });

            if (!res.ok) {
                const errText = await res.text().catch(() => '');
                progressLabel.textContent = `❌ Error (${res.status}): ${errText || 'Falló la conexión'}`;
                progressLabel.style.color = 'var(--accent-red)';
                btnConfirm.disabled = false;
                btnConfirm.innerHTML = '<i class="fa-solid fa-rotate-right"></i> Reintentar';
                return;
            }

            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let isError = false;

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                const chunk = decoder.decode(value, { stream: true });
                
                if (chunk.includes('Error') || chunk.includes('error')) {
                    isError = true;
                    progressLabel.textContent = chunk.trim();
                    progressLabel.style.color = 'var(--accent-red)';
                    btnConfirm.disabled = false;
                    btnConfirm.innerHTML = '<i class="fa-solid fa-rotate-right"></i> Reintentar';
                } else {
                    const matchPct = chunk.match(/\((\d+)%\)/);
                    if (matchPct && matchPct[1]) {
                        const pct = matchPct[1];
                        progressBar.style.width = `${pct}%`;
                        progressPct.textContent = `${pct}%`;
                    }

                    if (chunk.includes('success') || chunk.includes('verifying')) {
                        progressBar.style.width = '100%';
                        progressPct.textContent = '100%';
                        progressLabel.textContent = '¡Modelo instalado con éxito!';
                        progressLabel.style.color = 'var(--accent-green)';
                    } else {
                        progressLabel.textContent = chunk.split('\n')[0].substring(0, 60);
                    }
                }
            }

            if (!isError) {
                if (!this.installedModels.includes(modelName)) {
                    this.installedModels.push(modelName);
                }
                this.previousSelectedModel = modelName;
                if (typeof window.refreshAllModelLists === 'function') {
                    window.refreshAllModelLists(modelName);
                }
                setTimeout(() => {
                    this.closeDownloadModal(true);
                }, 1200);
            }

        } catch (e) {
            console.error("Error al descargar modelo:", e);
            progressLabel.textContent = `❌ Error de red / cliente: ${e.message || e}`;
            progressLabel.style.color = 'var(--accent-red)';
            btnConfirm.disabled = false;
            btnConfirm.innerHTML = '<i class="fa-solid fa-rotate-right"></i> Reintentar';
        }
    }

    async checkStatus(preferredModel = null) {
        try {
            const res = await fetch('/api/ai/status');
            const data = await res.json();

            if (data.online || data.status === 'ok') {
                this.statusDot.className = 'status-dot online';
                this.statusText.textContent = 'Ollama Activo';
                const existingHelp = document.getElementById('ollama-help-card');
                if (existingHelp) existingHelp.remove();

                const models = data.models || [];
                this.installedModels = models;

                if (this.modelSelect) {
                    const currentVal = preferredModel || this.modelSelect.value || this.previousSelectedModel || 'qwen2.5-coder:7b';
                    this.modelSelect.innerHTML = '';

                    // 1. Grupo de Modelos Instalados (listos para usar de inmediato)
                    if (models.length > 0) {
                        const grpInstalled = document.createElement('optgroup');
                        grpInstalled.label = '⚡ Modelos Instalados (Listos)';
                        grpInstalled.style.backgroundColor = '#181825';
                        grpInstalled.style.color = '#89b4fa';
                        models.forEach(m => {
                            const opt = document.createElement('option');
                            opt.value = m;
                            opt.textContent = `${m}`;
                            opt.style.backgroundColor = '#1e1e2e';
                            opt.style.color = '#cdd6f4';
                            grpInstalled.appendChild(opt);
                        });
                        this.modelSelect.appendChild(grpInstalled);
                    }

                    // 2. Grupo de Catálogo Recomendado (para descargar si aún no están)
                    const catalogPresets = [
                        'qwen3:14b', 'qwen3:8b', 'qwen3:4b',
                        'qwen2.5-coder:7b', 'qwen2.5-coder:14b', 'qwen2.5-coder:32b',
                        'deepseek-r1:8b', 'deepseek-r1:14b', 'deepseek-r1:1.5b', 'dolphin3:8b',
                        'hf.co/bartowski/OLMoE-1B-7B-0924-Instruct-GGUF:Q4_K_M', 'qwen3-coder:30b',
                        'hf.co/RichardErkhov/Qwen_-_Qwen1.5-MoE-A2.7B-Chat-gguf:Q4_K_M', 'deepseek-coder-v2:16b',
                        'qwen3.6:35b-a3b', 'hf.co/bartowski/Phi-3.5-MoE-instruct-GGUF:Q4_K_M', 'mixtral:8x7b',
                        'llama3.1:8b', 'mistral:7b'
                    ];
                    const notInstalled = catalogPresets.filter(p => !models.includes(p) && !models.includes(`${p}:latest`));
                    if (notInstalled.length > 0) {
                        const grpCatalog = document.createElement('optgroup');
                        grpCatalog.label = '⬇️ Descargar Modelo...';
                        grpCatalog.style.backgroundColor = '#181825';
                        grpCatalog.style.color = '#fab387';
                        notInstalled.forEach(m => {
                            const opt = document.createElement('option');
                            opt.value = m;
                            opt.textContent = `${m} (descargar)`;
                            opt.style.backgroundColor = '#1e1e2e';
                            opt.style.color = '#cdd6f4';
                            grpCatalog.appendChild(opt);
                        });
                        this.modelSelect.appendChild(grpCatalog);
                    }

                    // Seleccionar modelo deseado
                    const allOpts = Array.from(this.modelSelect.querySelectorAll('option')).map(o => o.value);
                    const match = allOpts.find(v => v === currentVal || v === `${currentVal}:latest` || currentVal.startsWith(v));
                    if (match) {
                        this.modelSelect.value = match;
                        this.previousSelectedModel = match;
                    } else if (models.length > 0) {
                        this.modelSelect.value = models[0];
                        this.previousSelectedModel = models[0];
                    }
                }
            } else {
                this.statusDot.className = 'status-dot offline';
                this.statusText.textContent = 'Ollama reconectando...';
            }
        } catch (e) {
            this.statusDot.className = 'status-dot offline';
            this.statusText.textContent = 'Sin conexión a Ollama';
        }
    }

    // ==========================================
    // MÉTODOS DEL SISTEMA DE GANCHO (HOOKED FILES)
    // ==========================================

    async openGanchoModal() {
        const modal = document.getElementById('modal-gancho-archivos');
        if (!modal) return;
        modal.style.display = 'flex';

        this.pendingHookedFiles = new Set(this.hookedFiles);

        const container = document.getElementById('gancho-tree-container');
        if (container) {
            container.innerHTML = '<div style="color: var(--text-muted); text-align: center; padding: 20px;"><i class="fa-solid fa-spinner fa-spin"></i> Cargando archivos del proyecto...</div>';
        }

        try {
            const res = await fetch('/api/tree');
            if (res.ok) {
                this.treeData = await res.json();
            }
        } catch (e) {
            console.error('Error cargando árbol para gancho:', e);
        }

        const searchInput = document.getElementById('gancho-search-input');
        if (searchInput) searchInput.value = '';

        this.renderGanchoTree(this.treeData);
        this.updateGanchoCounter();
    }

    closeGanchoModal() {
        const modal = document.getElementById('modal-gancho-archivos');
        if (modal) modal.style.display = 'none';
    }

    confirmGanchoSelection() {
        this.hookedFiles = new Set(this.pendingHookedFiles);
        this.closeGanchoModal();
        this.renderGanchoChips();
        this.updateGanchoBadge();
    }

    updateGanchoBadge() {
        const badge = document.getElementById('gancho-badge');
        const btn = document.getElementById('btn-chat-gancho');
        const count = this.hookedFiles.size;
        if (badge) {
            badge.textContent = count;
            badge.style.display = count > 0 ? 'inline-block' : 'none';
        }
        if (btn) {
            if (count > 0) {
                btn.style.background = 'rgba(137, 180, 250, 0.22)';
                btn.style.borderColor = 'var(--accent-blue)';
                btn.style.color = '#fff';
            } else {
                btn.style.background = '#252538';
                btn.style.borderColor = 'var(--accent-blue)';
                btn.style.color = '#cdd6f4';
            }
        }
    }

    renderGanchoChips() {
        const container = document.getElementById('gancho-chips-container');
        if (!container) return;
        container.innerHTML = '';
        if (this.hookedFiles.size === 0) {
            container.style.display = 'none';
            return;
        }

        container.style.display = 'flex';
        this.hookedFiles.forEach(filePath => {
            const name = filePath.split('/').pop();
            const chip = document.createElement('div');
            chip.className = 'gancho-chip';
            chip.title = filePath;
            chip.innerHTML = `
                <i class="fa-solid fa-file-code" style="color: var(--accent-blue); font-size: 10px;"></i>
                <span class="gancho-chip-name">${name}</span>
                <span class="gancho-chip-remove" title="Desenganchar archivo"><i class="fa-solid fa-xmark"></i></span>
            `;
            chip.querySelector('.gancho-chip-remove').onclick = (e) => {
                e.stopPropagation();
                this.unhookFile(filePath);
            };
            container.appendChild(chip);
        });

        if (this.hookedFiles.size > 1) {
            const clearBtn = document.createElement('button');
            clearBtn.type = 'button';
            clearBtn.style.cssText = 'background: transparent; border: none; color: var(--text-muted); font-size: 10px; cursor: pointer; text-decoration: underline; padding: 2px 4px;';
            clearBtn.textContent = 'Limpiar todo';
            clearBtn.onclick = () => {
                this.hookedFiles.clear();
                this.renderGanchoChips();
                this.updateGanchoBadge();
            };
            container.appendChild(clearBtn);
        }
    }

    unhookFile(filePath) {
        this.hookedFiles.delete(filePath);
        this.renderGanchoChips();
        this.updateGanchoBadge();
    }

    getAllFilePaths(item) {
        const paths = [];
        const binaryExts = ['.png', '.jpg', '.jpeg', '.gif', '.ico', '.pdf', '.zip', '.tar', '.gz', '.exe', '.bin', '.db', '.sqlite', '.sqlite3', '.pyc', '.wasm'];
        const recurse = (node) => {
            if (node.is_dir) {
                if (node.children) {
                    node.children.forEach(child => recurse(child));
                }
            } else if (node.path) {
                const lower = (node.name || '').toLowerCase();
                if (!binaryExts.some(ext => lower.endsWith(ext))) {
                    paths.push(node.path);
                }
            }
        };
        recurse(item);
        return paths;
    }

    renderGanchoTree(items, filterTerm = '') {
        const container = document.getElementById('gancho-tree-container');
        if (!container) return;
        container.innerHTML = '';

        if (!items || items.length === 0) {
            container.innerHTML = '<div style="color: var(--text-muted); text-align: center; padding: 20px;">No se encontraron archivos en el espacio de trabajo</div>';
            return;
        }

        const matchesFilter = (item) => {
            if (!filterTerm) return true;
            if (item.name && item.name.toLowerCase().includes(filterTerm)) return true;
            if (item.is_dir && item.children) {
                return item.children.some(c => matchesFilter(c));
            }
            return false;
        };

        const buildNode = (item, level = 0) => {
            if (filterTerm && !matchesFilter(item)) return null;

            const nodeWrapper = document.createElement('div');
            nodeWrapper.style.cssText = `display: flex; flex-direction: column;`;

            const row = document.createElement('div');
            row.className = 'gancho-tree-item';
            row.style.paddingLeft = `${level * 16 + 6}px`;

            const chk = document.createElement('input');
            chk.type = 'checkbox';

            if (item.is_dir) {
                const descendantPaths = this.getAllFilePaths(item);
                const allSelected = descendantPaths.length > 0 && descendantPaths.every(p => this.pendingHookedFiles.has(p));
                const someSelected = descendantPaths.some(p => this.pendingHookedFiles.has(p));

                chk.checked = allSelected;
                chk.indeterminate = !allSelected && someSelected;

                chk.onchange = (e) => {
                    const checkState = e.target.checked;
                    descendantPaths.forEach(p => {
                        if (checkState) {
                            this.pendingHookedFiles.add(p);
                        } else {
                            this.pendingHookedFiles.delete(p);
                        }
                    });
                    this.refreshGanchoTreeCheckboxes();
                    this.updateGanchoCounter();
                };

                const toggleIcon = document.createElement('i');
                toggleIcon.className = 'fa-solid fa-chevron-right';
                toggleIcon.style.cssText = 'font-size: 9px; width: 12px; color: var(--text-muted); cursor: pointer; transition: transform 0.15s;';
                if (filterTerm) toggleIcon.className = 'fa-solid fa-chevron-down';

                const folderIcon = document.createElement('i');
                folderIcon.className = 'fa-solid fa-folder';
                folderIcon.style.cssText = 'color: var(--accent-yellow); font-size: 12px; margin-right: 2px;';

                const label = document.createElement('span');
                label.textContent = item.name;
                label.style.cssText = 'color: #cdd6f4; font-weight: 500; flex: 1; cursor: pointer;';

                row.appendChild(toggleIcon);
                row.appendChild(chk);
                row.appendChild(folderIcon);
                row.appendChild(label);
                nodeWrapper.appendChild(row);

                const childrenContainer = document.createElement('div');
                childrenContainer.style.display = filterTerm ? 'flex' : 'none';
                childrenContainer.style.flexDirection = 'column';

                const toggleFolder = () => {
                    const isExpanded = childrenContainer.style.display !== 'none';
                    childrenContainer.style.display = isExpanded ? 'none' : 'flex';
                    toggleIcon.className = isExpanded ? 'fa-solid fa-chevron-right' : 'fa-solid fa-chevron-down';
                };

                toggleIcon.onclick = (e) => { e.stopPropagation(); toggleFolder(); };
                label.onclick = () => toggleFolder();

                if (item.children) {
                    item.children.forEach(child => {
                        const childNode = buildNode(child, level + 1);
                        if (childNode) childrenContainer.appendChild(childNode);
                    });
                }
                nodeWrapper.appendChild(childrenContainer);

            } else {
                // Archivo individual
                chk.checked = this.pendingHookedFiles.has(item.path);
                chk.onchange = (e) => {
                    if (e.target.checked) {
                        this.pendingHookedFiles.add(item.path);
                    } else {
                        this.pendingHookedFiles.delete(item.path);
                    }
                    this.refreshGanchoTreeCheckboxes();
                    this.updateGanchoCounter();
                };

                const spacer = document.createElement('span');
                spacer.style.width = '12px';

                const fileIcon = document.createElement('i');
                fileIcon.className = 'fa-solid fa-file-code';
                fileIcon.style.cssText = 'color: var(--accent-blue); font-size: 11px; margin-right: 2px;';

                const label = document.createElement('span');
                label.textContent = item.name;
                label.style.cssText = 'color: #bac2de; flex: 1; cursor: pointer;';
                label.onclick = () => {
                    chk.checked = !chk.checked;
                    chk.dispatchEvent(new Event('change'));
                };

                row.appendChild(spacer);
                row.appendChild(chk);
                row.appendChild(fileIcon);
                row.appendChild(label);
                nodeWrapper.appendChild(row);
            }

            return nodeWrapper;
        };

        items.forEach(item => {
            const node = buildNode(item, 0);
            if (node) container.appendChild(node);
        });
    }

    refreshGanchoTreeCheckboxes() {
        const searchInput = document.getElementById('gancho-search-input');
        const term = searchInput ? searchInput.value.trim().toLowerCase() : '';
        this.renderGanchoTree(this.treeData, term);
    }

    updateGanchoCounter() {
        const counter = document.getElementById('gancho-counter-text');
        if (counter) {
            const count = this.pendingHookedFiles.size;
            counter.textContent = `${count} archivo${count === 1 ? '' : 's'} seleccionado${count === 1 ? '' : 's'}`;
        }
    }

    filterGanchoTree(term) {
        this.renderGanchoTree(this.treeData, term);
    }

    ganchoSelectActiveFile() {
        if (window.editorMgr && window.editorMgr.activePath) {
            this.pendingHookedFiles.add(window.editorMgr.activePath);
            this.refreshGanchoTreeCheckboxes();
            this.updateGanchoCounter();
        }
    }

    ganchoSelectAll() {
        if (!this.treeData) return;
        this.treeData.forEach(item => {
            const paths = this.getAllFilePaths(item);
            paths.forEach(p => this.pendingHookedFiles.add(p));
        });
        this.refreshGanchoTreeCheckboxes();
        this.updateGanchoCounter();
    }

    ganchoClearAll() {
        this.pendingHookedFiles.clear();
        this.refreshGanchoTreeCheckboxes();
        this.updateGanchoCounter();
    }

    async writeFileDirectly(btnEl, targetPath) {
        const wrapper = btnEl.closest('.code-block-wrapper');
        if (!wrapper) return;
        const codeBlock = wrapper.querySelector('code');
        const codeText = codeBlock ? codeBlock.innerText : wrapper.innerText;
        const originalHtml = btnEl.innerHTML;
        btnEl.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Guardando...';
        btnEl.disabled = true;

        try {
            const res = await fetch('/api/file', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: targetPath, content: codeText })
            });

            if (!res.ok) {
                const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
                throw new Error(err.detail || 'Error al guardar archivo');
            }

            // Si está abierto en el editor, actualizar su contenido y marcar guardado
            if (window.editorMgr) {
                const tab = window.editorMgr.openTabs.get(targetPath);
                if (tab && tab.model) {
                    tab.model.setValue(codeText);
                    window.editorMgr.markSaved(targetPath, codeText);
                }
            }

            const fileName = targetPath.split('/').pop();
            btnEl.innerHTML = `<i class="fa-solid fa-check"></i> ¡Guardado en ${fileName}!`;
            btnEl.style.color = 'var(--accent-green)';
            if (window.terminalMgr) {
                window.terminalMgr.appendLine(`[Prig Gancho] Código guardado exitosamente en: ${targetPath}`, 'stdout');
            }
            setTimeout(() => {
                btnEl.innerHTML = originalHtml;
                btnEl.disabled = false;
            }, 3000);
        } catch (e) {
            console.error('Error escribiendo en archivo enganchado:', e);
            btnEl.innerHTML = `<i class="fa-solid fa-triangle-exclamation"></i> Error`;
            btnEl.style.color = 'var(--accent-red)';
            if (window.terminalMgr) {
                window.terminalMgr.appendLine(`[Prig Gancho Error] ${e.message}`, 'stderr');
            }
            setTimeout(() => {
                btnEl.innerHTML = originalHtml;
                btnEl.disabled = false;
            }, 3000);
        }
    }

    promptWriteCodeToFile(btnEl) {
        if (!this.hookedFiles || this.hookedFiles.size === 0) return;
        if (this.hookedFiles.size === 1) {
            const targetPath = Array.from(this.hookedFiles)[0];
            return this.writeFileDirectly(btnEl, targetPath);
        }

        const menuExistente = document.getElementById('menu-gancho-select-file');
        if (menuExistente) menuExistente.remove();

        const rect = btnEl.getBoundingClientRect();
        const menu = document.createElement('div');
        menu.id = 'menu-gancho-select-file';
        menu.style.cssText = `position: fixed; top: ${rect.bottom + 4}px; left: ${Math.max(10, rect.left - 40)}px; background: #1e1e2e; border: 1px solid var(--accent-blue); border-radius: 6px; padding: 6px 0; z-index: 10000; box-shadow: 0 8px 24px rgba(0,0,0,0.7); max-width: 300px; max-height: 220px; overflow-y: auto; font-size: 11px;`;

        const titulo = document.createElement('div');
        titulo.style.cssText = 'padding: 4px 10px; color: var(--text-muted); font-size: 10px; border-bottom: 1px solid #313244; font-weight: 600;';
        titulo.textContent = 'Selecciona archivo de destino:';
        menu.appendChild(titulo);

        this.hookedFiles.forEach(path => {
            const item = document.createElement('div');
            item.style.cssText = 'padding: 6px 10px; color: #cdd6f4; cursor: pointer; display: flex; align-items: center; gap: 6px; white-space: nowrap; text-overflow: ellipsis; overflow: hidden;';
            item.onmouseover = () => { item.style.background = 'rgba(137,180,250,0.15)'; };
            item.onmouseout = () => { item.style.background = 'transparent'; };
            const fname = path.split('/').pop();
            item.innerHTML = `<i class="fa-solid fa-file-code" style="color: var(--accent-blue);"></i> <span title="${path}">${fname}</span>`;
            item.onclick = (e) => {
                e.stopPropagation();
                menu.remove();
                this.writeFileDirectly(btnEl, path);
            };
            menu.appendChild(item);
        });

        document.body.appendChild(menu);
        const cerrar = (e) => {
            if (!menu.contains(e.target) && e.target !== btnEl) {
                menu.remove();
                document.removeEventListener('click', cerrar);
            }
        };
        setTimeout(() => document.addEventListener('click', cerrar), 10);
    }

    appendOfflineHelp(reasonText) {
        if (document.getElementById('ollama-help-card')) return;
        const helpDiv = document.createElement('div');
        helpDiv.id = 'ollama-help-card';
        helpDiv.style.cssText = 'background: rgba(243, 139, 168, 0.1); border: 1px solid var(--accent-red); padding: 12px; border-radius: 8px; font-size: 11px; margin-bottom: 10px; line-height: 1.5;';
        helpDiv.innerHTML = `
            <strong style="color:var(--accent-red); font-size: 12px;">⚠️ ${reasonText}</strong><br><br>
            Para activar la IA local gratuita en tu Ubuntu:<br>
            1. Abre una terminal y ejecuta:<br>
            <code style="background:#11111b; padding:4px 8px; border-radius:4px; display:inline-block; margin:4px 0; color:var(--accent-yellow); font-family:monospace;">curl -fsSL https://ollama.com/install.sh | sh</code><br>
            2. Descarga el modelo recomendado:<br>
            <code style="background:#11111b; padding:4px 8px; border-radius:4px; display:inline-block; margin:4px 0; color:var(--accent-green); font-family:monospace;">ollama pull qwen2.5-coder:7b</code><br><br>
            3. Haz clic aquí para <a href="#" onclick="window.aiChatMgr.checkStatus(); return false;" style="color:var(--accent-blue);">reintentar conexión</a>.
        `;
        this.messagesContainer.prepend(helpDiv);
    }

    appendMessage(text, isUser = false) {
        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${isUser ? 'user-msg' : 'ai-msg'}`;

        const authorDiv = document.createElement('div');
        authorDiv.className = 'msg-author';
        authorDiv.innerHTML = isUser ? '<i class="fa-solid fa-user"></i> Tú' : '<i class="fa-solid fa-brain"></i> Tutor Prig';

        const contentDiv = document.createElement('div');
        contentDiv.className = 'msg-content markdown-rendered';
        contentDiv.innerHTML = this.renderMarkdown(text);

        msgDiv.appendChild(authorDiv);
        msgDiv.appendChild(contentDiv);
        this.messagesContainer.appendChild(msgDiv);
        this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight;
        return contentDiv;
    }

    renderMarkdown(text) {
        if (!text) return '';

        let contentToParse = text;

        const fenceMatches = contentToParse.match(/```/g);
        const fenceCount = fenceMatches ? fenceMatches.length : 0;
        if (fenceCount % 2 !== 0) {
            contentToParse += '\n```';
        }

        let parsedHtml = '';
        try {
            if (typeof marked !== 'undefined') {
                parsedHtml = marked.parse(contentToParse);
            } else {
                parsedHtml = this.fallbackMarkdown(contentToParse);
            }
        } catch (e) {
            parsedHtml = this.fallbackMarkdown(contentToParse);
        }

        // El markdown viene del modelo y de páginas web raspadas: sanear antes de
        // insertarlo evita que una respuesta maliciosa ejecute JS con acceso a la API local.
        if (typeof DOMPurify !== 'undefined') {
            parsedHtml = DOMPurify.sanitize(parsedHtml, { USE_PROFILES: { html: true, svg: true, mathMl: true } });
        }

        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = parsedHtml;

        tempDiv.querySelectorAll('pre code').forEach((codeBlock) => {
            if (codeBlock.closest('.code-block-wrapper')) return;

            const langMatch = codeBlock.className.match(/language-(\w+)/);
            const lang = langMatch ? langMatch[1] : 'código';

            let writeButtonHtml = '';
            if (this.hookedFiles && this.hookedFiles.size > 0) {
                let detectedTarget = null;
                for (const hPath of this.hookedFiles) {
                    const fname = hPath.split('/').pop();
                    if (codeBlock.textContent.includes(fname) || contentToParse.includes(hPath) || contentToParse.includes(fname)) {
                        detectedTarget = hPath;
                        break;
                    }
                }
                if (!detectedTarget && this.hookedFiles.size === 1) {
                    detectedTarget = Array.from(this.hookedFiles)[0];
                }

                if (detectedTarget) {
                    const targetFname = detectedTarget.split('/').pop();
                    writeButtonHtml = `
                        <button class="btn-write-file" data-target="${detectedTarget}" onclick="window.aiChatMgr.writeFileDirectly(this, '${detectedTarget.replace(/'/g, "\\'")}')" title="Guardar cambios directamente en ${detectedTarget}" style="background: rgba(166,227,161,0.15); color: var(--accent-green); border: 1px solid var(--accent-green); border-radius: 4px; padding: 2px 6px; cursor: pointer; font-size: 11px; font-weight: 600;">
                            <i class="fa-solid fa-floppy-disk"></i> Escribir en ${targetFname}
                        </button>
                    `;
                } else {
                    writeButtonHtml = `
                        <button class="btn-write-file" onclick="window.aiChatMgr.promptWriteCodeToFile(this)" title="Escribir en uno de los archivos enganchados..." style="background: rgba(166,227,161,0.15); color: var(--accent-green); border: 1px solid var(--accent-green); border-radius: 4px; padding: 2px 6px; cursor: pointer; font-size: 11px; font-weight: 600;">
                            <i class="fa-solid fa-floppy-disk"></i> Escribir en archivo...
                        </button>
                    `;
                }
            }

            const wrapper = document.createElement('div');
            wrapper.className = 'code-block-wrapper';

            const header = document.createElement('div');
            header.className = 'code-block-header';
            header.style.cssText = 'display: flex; justify-content: space-between; align-items: center; background: rgba(0,0,0,0.3); padding: 4px 8px; border-bottom: 1px solid var(--border-color); font-size: 11px;';
            header.innerHTML = `
                <span><i class="fa-solid fa-code"></i> ${lang.toUpperCase()}</span>
                <div style="display: flex; gap: 6px; align-items: center;">
                    <button class="btn-copy-code" onclick="window.aiChatMgr.copyCodeToClipboard(this)" style="background: transparent; border: none; color: var(--text-muted); cursor: pointer; font-size: 11px;">
                        <i class="fa-regular fa-copy"></i> Copiar
                    </button>
                    <button class="btn-insert-code" onclick="window.aiChatMgr.insertCodeToActiveTarget(this)" style="background: rgba(137,180,250,0.15); color: var(--accent-blue); border: 1px solid var(--accent-blue); border-radius: 4px; padding: 2px 6px; cursor: pointer; font-size: 11px; font-weight: 600;">
                        <i class="fa-solid fa-file-import"></i> Insertar en Editor / Notebook
                    </button>
                    ${writeButtonHtml}
                </div>
            `;

            const pre = codeBlock.parentNode;
            pre.parentNode.insertBefore(wrapper, pre);
            wrapper.appendChild(header);
            wrapper.appendChild(pre);

            if (typeof hljs !== 'undefined') {
                hljs.highlightElement(codeBlock);
            }
        });

        return tempDiv.innerHTML;
    }

    copyCodeToClipboard(btnEl) {
        const wrapper = btnEl.closest('.code-block-wrapper');
        if (!wrapper) return;
        const codeText = wrapper.querySelector('code').innerText;
        this.copiarTexto(codeText).then((ok) => {
            btnEl.innerHTML = ok ? '<i class="fa-solid fa-check"></i> ¡Copiado!' : '<i class="fa-solid fa-xmark"></i> No se pudo copiar';
            setTimeout(() => {
                btnEl.innerHTML = '<i class="fa-regular fa-copy"></i> Copiar';
            }, 2000);
        });
    }

    insertCodeToActiveTarget(btnEl) {
        const wrapper = btnEl.closest('.code-block-wrapper');
        if (!wrapper) return;
        const codeText = wrapper.querySelector('code')?.innerText || wrapper.innerText;
        const etiqueta = (html) => {
            btnEl.innerHTML = html;
            setTimeout(() => { btnEl.innerHTML = '<i class="fa-solid fa-file-import"></i> Insertar en Editor / Notebook'; }, 2500);
        };
        const ed = window.editorMgr;
        const ruta = ed && ed.activePath;
        // Si hay una herramienta en primer plano, se vuelve al editor para ver el resultado
        const alEditor = () => { if (window.workArea && window.workArea.activa !== 'editor') window.workArea.activar('editor'); };

        try {
            // 1. Cuaderno abierto: nueva celda de código
            if (ruta && ruta.endsWith('.ipynb') && window.notebookMgr && window.notebookMgr.activeNotebookPath === ruta) {
                alEditor();
                if (window.notebookMgr.addCell('code', codeText)) return etiqueta('<i class="fa-solid fa-check"></i> ¡Nueva celda en el cuaderno!');
            }
            // 2. Archivo de código abierto: en la posición del cursor
            if (ruta && !ruta.endsWith('.ipynb') && ed.editor && ed.editor.getModel()) {
                alEditor();
                const editor = ed.editor;
                const position = editor.getPosition() || { lineNumber: 1, column: 1 };
                editor.executeEdits('ai-chat-insert', [{
                    range: new monaco.Range(position.lineNumber, position.column, position.lineNumber, position.column),
                    text: '\n' + codeText + '\n'
                }]);
                editor.focus();
                return etiqueta('<i class="fa-solid fa-check"></i> ¡Insertado en el editor!');
            }
        } catch (e) {
            console.error('No se pudo insertar el código:', e);
        }

        // 3. Nada abierto: se copia y se dice en el propio botón (sin alert, que bloquea la ventana)
        this.copiarTexto(codeText).then((ok) => etiqueta(ok
            ? '<i class="fa-regular fa-clipboard"></i> Copiado: abre un archivo o cuaderno para insertarlo'
            : '<i class="fa-solid fa-triangle-exclamation"></i> Abre un archivo o cuaderno para insertarlo'));
    }

    /** Copia al portapapeles sin depender de navigator.clipboard (puede faltar o pedir permiso) */
    async copiarTexto(texto) {
        try {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                await navigator.clipboard.writeText(texto);
                return true;
            }
        } catch (e) { /* se intenta a la antigua */ }
        try {
            const area = document.createElement('textarea');
            area.value = texto;
            area.style.cssText = 'position:fixed; left:-9999px; top:0;';
            document.body.appendChild(area);
            area.select();
            const ok = document.execCommand('copy');
            area.remove();
            return ok;
        } catch (e) {
            return false;
        }
    }

    async diagnoseErrorWithWeb(errorText) {
        if (!errorText) return;
        // Abrir panel lateral de IA si está cerrado
        if (window.app && window.app.toggleAISidebar) {
            window.app.toggleAISidebar(false);
        }

        // Forzar activación del checkbox de Búsqueda Web
        const chkWeb = document.getElementById('chk-web-search');
        if (chkWeb) chkWeb.checked = true;

        const prompt = `Analiza y diagnostica el siguiente ERROR O TRACEBACK de ejecución. Busca la solución oficial en internet, explica por qué ocurrió y proporciona el código corregido:\n\n\`\`\`\n${errorText}\n\`\`\``;
        await this.sendMessage(prompt, "chat");
    }

    fallbackMarkdown(text) {
        let html = text;
        html = html.replace(/^# (.*$)/gim, '<h1>$1</h1>');
        html = html.replace(/^## (.*$)/gim, '<h2>$1</h2>');
        html = html.replace(/^### (.*$)/gim, '<h3>$1</h3>');
        const parts = html.split(/```/);
        for (let i = 0; i < parts.length; i++) {
            if (i % 2 !== 0) {
                parts[i] = '<pre><code>' + parts[i] + '</code></pre>';
            } else {
                parts[i] = parts[i]
                    .replace(/`([^`]+)`/g, '<code>$1</code>')
                    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
                    .replace(/\n/g, '<br>');
            }
        }
        return parts.join('');
    }

    /**
     * Respuesta fundamentada en la biblioteca del usuario.
     *
     * Usa /api/knowledge/ask, que emite NDJSON: primero las fuentes —para poder
     * pintarlas mientras el modelo redacta— y luego los tokens de la respuesta.
     */
    async sendLibraryMessage(prompt, model) {
        const contentEl = this.appendMessage(
            '<span style="color: var(--accent-purple);"><i class="fa-solid fa-book-bookmark fa-fade"></i> Buscando en tu biblioteca…</span>',
            false
        );

        try {
            const res = await fetch('/api/knowledge/ask', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query: prompt, model, top_k: 6, expand: true })
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);

            const reader = res.body.getReader();
            const decoder = new TextDecoder('utf-8');
            let buffer = '';
            let texto = '';
            let fuentesHtml = '';

            const pintar = () => {
                contentEl.innerHTML = fuentesHtml + this.renderMarkdown(texto);
                this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight;
            };

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });

                let corte;
                while ((corte = buffer.indexOf('\n')) >= 0) {
                    const linea = buffer.slice(0, corte).trim();
                    buffer = buffer.slice(corte + 1);
                    if (!linea) continue;

                    let ev;
                    try { ev = JSON.parse(linea); } catch (e) { continue; }

                    if (ev.type === 'sources') {
                        fuentesHtml = this.renderFuentes(ev);
                        contentEl.innerHTML = fuentesHtml;
                    } else if (ev.type === 'token') {
                        texto += ev.text;
                        pintar();
                    }
                }
            }
            pintar();
        } catch (e) {
            contentEl.innerHTML = `<span style="color: var(--accent-red);">No se pudo consultar la biblioteca: ${String(e.message)
                .replace(/&/g,'&amp;').replace(/</g,'&lt;')}</span>`;
        }
    }

    /** Tarjetas de fuente: título del libro, página y acceso al lector */
    renderFuentes(ev) {
        const esc = (t) => String(t ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

        if (!ev.found || !ev.chunks || ev.chunks.length === 0) {
            return `<div style="background: rgba(249,226,175,0.10); border:1px solid rgba(249,226,175,0.3); border-radius:6px; padding:8px 10px; font-size:11px; color: var(--accent-yellow); margin-bottom:10px;">
                <i class="fa-solid fa-circle-info"></i> No encontré nada sobre esto en tu biblioteca.
                Comprueba que el material esté indexado en <strong>Biblioteca</strong>.
            </div>`;
        }

        const tarjetas = ev.chunks.map(ch => `
            <button class="fuente-chip" onclick="window.aiChatMgr.abrirFuente('${esc(ch.source_title).replace(/'/g, "\\'")}')"
                title="${esc(ch.preview)}"
                style="text-align:left; background: rgba(203,166,247,0.10); border:1px solid rgba(203,166,247,0.3); color: var(--text-main); border-radius:5px; padding:5px 8px; font-size:10px; cursor:pointer; line-height:1.4;">
                <strong style="color: var(--accent-purple);">[${ch.n}]</strong>
                ${esc(ch.source_title)} · pág. ${esc(ch.page)}
            </button>`).join('');

        const t = ev.stats || {};
        return `<div style="margin-bottom:10px;">
            <div style="font-size:10px; color: var(--text-muted); margin-bottom:5px; letter-spacing:0.04em;">
                <i class="fa-solid fa-book-bookmark" style="color: var(--accent-purple);"></i>
                FUENTES DE TU BIBLIOTECA · ${t.estimated_tokens || 0}/${t.token_budget || 0} tokens
            </div>
            <div style="display:flex; flex-wrap:wrap; gap:5px;">${tarjetas}</div>
        </div>`;
    }

    /** Abre la biblioteca en el documento citado */
    abrirFuente(titulo) {
        if (!window.bookLibraryMgr) return;
        window.bookLibraryMgr.openModal();
        setTimeout(() => {
            const libro = (window.bookLibraryMgr.allBooks || [])
                .find(b => b.title === titulo || b.filename === titulo);
            if (libro) window.bookLibraryMgr.openBook(window.bookLibraryMgr.bookKey(libro));
        }, 400);
    }

    /**
     * Las explicaciones que se piden desde el editor o el cuaderno usan el modelo de
     * «Explicar» y los arreglos de errores el de «Código» (Configuración global). El
     * chat normal, el del selector de este panel.
     */
    modeloPara(mode) {
        const delPanel = (this.modelSelect && this.modelSelect.value) || "qwen2.5-coder:7b";
        const rol = { explain: 'explicar', explain_flow: 'explicar', fix: 'codigo' }[mode];
        return (rol && window.PrigModelos) ? window.PrigModelos.para(rol, delPanel) : delPanel;
    }

    async sendMessage(customPrompt = null, mode = "chat", codeContext = null) {
        const prompt = customPrompt || this.inputEl.value.trim();
        if (!prompt) return;

        if (!customPrompt) this.inputEl.value = '';

        this.appendMessage(prompt, true);

        const chkWeb = document.getElementById('chk-web-search');
        const useWeb = chkWeb ? chkWeb.checked : false;
        const chkLib = document.getElementById('chk-usar-biblioteca');
        const useLibrary = chkLib ? chkLib.checked : false;

        const model = this.modeloPara(mode);

        // Con la biblioteca activada la respuesta va fundamentada en los documentos
        // del usuario y con citas verificables, que es la diferencia real frente a
        // cualquier chat genérico.
        if (useLibrary) {
            return this.sendLibraryMessage(prompt, model);
        }

        const initialStatus = useWeb 
            ? '<span style="color: var(--accent-blue);"><i class="fa-solid fa-globe fa-spin"></i> Buscando información en fuentes oficiales de Internet...</span>'
            : (model !== (this.modelSelect && this.modelSelect.value)
                ? `Analizando con <b>${model.replace(/[<>&]/g, '')}</b> (el modelo para ${mode === 'fix' ? 'escribir código' : 'explicar'})...`
                : 'Analizando con detalle...');

        const aiMsgContentEl = this.appendMessage(initialStatus, false);
        const currentCode = codeContext || (window.editorMgr && typeof window.editorMgr.getAIContext === 'function' ? window.editorMgr.getAIContext() : '');

        // Recolectar archivos enganchados para contexto y edición asistida
        let hookedFilesData = [];
        if (this.hookedFiles && this.hookedFiles.size > 0) {
            for (const filePath of this.hookedFiles) {
                let content = null;
                if (window.editorMgr && window.editorMgr.openTabs.has(filePath)) {
                    content = window.editorMgr.openTabs.get(filePath).model.getValue();
                } else {
                    try {
                        const res = await fetch(`/api/file?path=${encodeURIComponent(filePath)}`);
                        if (res.ok) {
                            const data = await res.json();
                            content = data.content;
                        }
                    } catch (e) {
                        console.warn(`No se pudo leer archivo enganchado ${filePath}:`, e);
                    }
                }
                if (content !== null && content !== undefined) {
                    hookedFilesData.push({
                        path: filePath,
                        name: filePath.split('/').pop(),
                        content: content
                    });
                }
            }
        }

        const cuerpo = {
            prompt, model, mode, code_context: currentCode, use_web: useWeb,
            eventos: true, ...this.opcionesChat(model),
            hooked_files: hookedFilesData.length > 0 ? hookedFilesData : undefined
        };
        await this.pedirEventos(cuerpo, aiMsgContentEl, '');
    }

    /** Opciones del chat según lo que sabe hacer el modelo elegido */
    opcionesChat(model) {
        const caps = this.capacidades[model] || [];
        const marcado = (id) => { const el = document.getElementById(id); return !!(el && el.checked && !el.closest('[hidden]')); };
        const opciones = {};
        if (caps.includes('thinking')) opciones.think = marcado('chk-pensar');
        if (marcado('chk-confianza')) opciones.logprobs = 3;
        if (caps.includes('tools') && marcado('chk-herramientas')) {
            opciones.herramientas = true;
            opciones.permitir_codigo = marcado('chk-permitir-codigo');
        }
        return opciones;
    }

    /** Capacidades de los modelos instalados, para mostrar solo las opciones que aplican */
    async cargarCapacidades() {
        try {
            const d = await prigFetchJson('/api/modelos');
            this.capacidades = {};
            d.modelos.forEach(m => { this.capacidades[m.nombre] = m.capacidades; });
        } catch (e) { this.capacidades = this.capacidades || {}; }
        this.pintarOpcionesModelo();
    }

    pintarOpcionesModelo() {
        const model = this.modelSelect ? this.modelSelect.value : '';
        const caps = (this.capacidades || {})[model] || [];
        const mostrar = (id, si) => { const el = document.getElementById(id); if (el) el.hidden = !si; };
        mostrar('opc-pensar', caps.includes('thinking'));
        mostrar('opc-herramientas', caps.includes('tools'));
        const herr = document.getElementById('chk-herramientas');
        mostrar('opc-permitir-codigo', caps.includes('tools') && herr && herr.checked);
    }

    /**
     * Pide al backend y va pintando los eventos: texto, razonamiento, herramientas,
     * confianza y métricas. `previo` es lo ya escrito cuando se continúa una
     * respuesta cortada por el límite de tokens.
     */
    async pedirEventos(cuerpo, contentEl, previo) {
        const msgEl = contentEl.closest('.message');
        let razonamiento = msgEl.querySelector('.msg-razonamiento');
        let herramientasEl = msgEl.querySelector('.msg-herramientas');
        let pensamiento = razonamiento ? razonamiento.dataset.texto || '' : '';
        let fullResponse = previo || '';
        let logprobs = msgEl._logprobs || [];
        let stats = null;
        const avisos = [];

        const asegurar = (clase, html) => {
            let el = msgEl.querySelector(`.${clase}`);
            if (!el) {
                el = document.createElement('div');
                el.className = clase;
                el.innerHTML = html;
                msgEl.insertBefore(el, contentEl);
            }
            return el;
        };
        const pintar = () => {
            contentEl.innerHTML = this.renderMarkdown(fullResponse || '');
            this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight;
        };

        try {
            const res = await fetch('/api/ai/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                                     body: JSON.stringify(cuerpo) });
            if (!res.ok) throw new Error(await prigErrorDetail(res));
            if (!previo) contentEl.innerHTML = '';
            const lector = res.body.getReader();
            const dec = new TextDecoder('utf-8');
            let resto = '';
            for (;;) {
                const { done, value } = await lector.read();
                if (done) break;
                resto += dec.decode(value, { stream: true });
                const lineas = resto.split('\n');
                resto = lineas.pop();
                for (const linea of lineas) {
                    if (!linea.trim()) continue;
                    let ev;
                    try { ev = JSON.parse(linea); } catch (e) { continue; }
                    if (ev.t === 'texto') { fullResponse += ev.v; pintar(); }
                    else if (ev.t === 'pensando') {
                        razonamiento = asegurar('msg-razonamiento', `<details style="margin:4px 0 6px; font-size:11px; color:var(--text-muted);">
                            <summary style="cursor:pointer;"><i class="fa-solid fa-lightbulb"></i> Razonamiento</summary>
                            <div class="razonamiento-texto" style="white-space:pre-wrap; margin-top:4px; max-height:220px; overflow:auto;"></div></details>`);
                        pensamiento += ev.v;
                        razonamiento.dataset.texto = pensamiento;
                        razonamiento.querySelector('.razonamiento-texto').textContent = pensamiento;
                    } else if (ev.t === 'herramienta') {
                        herramientasEl = asegurar('msg-herramientas', '');
                        const fila = document.createElement('div');
                        fila.style.cssText = 'font-size:11px; color:var(--accent-blue); margin:2px 0;';
                        fila.innerHTML = `<i class="fa-solid fa-screwdriver-wrench"></i> <span></span>`;
                        fila.querySelector('span').textContent = `${ev.etiqueta || ev.nombre} ${JSON.stringify(ev.argumentos || {})}`;
                        herramientasEl.appendChild(fila);
                    } else if (ev.t === 'resultado') {
                        const det = document.createElement('details');
                        det.style.cssText = 'font-size:10.5px; color:var(--text-muted); margin:0 0 4px 16px;';
                        det.innerHTML = '<summary style="cursor:pointer;">resultado</summary><pre style="white-space:pre-wrap; max-height:160px; overflow:auto; margin:2px 0;"></pre>';
                        det.querySelector('pre').textContent = ev.v;
                        (herramientasEl || asegurar('msg-herramientas', '')).appendChild(det);
                    } else if (ev.t === 'logprobs') { logprobs = logprobs.concat(ev.v); }
                    else if (ev.t === 'stats') { stats = ev.v; }
                    else if (ev.t === 'aviso') { avisos.push(ev.v); }
                    else if (ev.t === 'termico') {
                        // Pausa del gobernador térmico: la respuesta sigue sola al enfriarse la GPU
                        const t = asegurar('msg-termico', '<div style="font-size:11px; color:var(--accent-yellow); margin:2px 0 6px;"><i class="fa-solid fa-temperature-half"></i> <span></span></div>');
                        t.querySelector('span').textContent = ev.v;
                        t.style.opacity = ev.pausa ? '1' : '0.6';
                    }
                    else if (ev.t === 'error') { throw new Error(ev.v); }
                }
            }
            msgEl._logprobs = logprobs;
            this.finalizarRespuesta(contentEl, fullResponse, { stats, avisos, logprobs, cuerpo });
        } catch (e) {
            contentEl.innerHTML = this.renderMarkdown(fullResponse || '') +
                `<div style="color:var(--accent-red); margin-top:6px;">Error al comunicarse con Ollama: ${String(e.message || e).replace(/</g, '&lt;')}</div>`;
        }
    }

    finalizarRespuesta(contentEl, fullResponse, { stats, avisos, logprobs, cuerpo }) {
        const msgEl = contentEl.closest('.message');
        msgEl.querySelectorAll('.msg-pie').forEach(x => x.remove());

        if (typeof mermaid !== 'undefined') {
            contentEl.querySelectorAll('pre code.language-mermaid, pre.mermaid').forEach((block, idx) => {
                const code = block.textContent;
                const parent = block.tagName.toLowerCase() === 'code' ? block.parentNode : block;
                const div = document.createElement('div');
                div.className = 'mermaid-rendered';
                div.style.cssText = 'background: rgba(0,0,0,0.3); padding: 12px; border-radius: 8px; margin: 10px 0; text-align: center; border: 1px solid var(--border-color);';
                div.id = `mermaid-chat-${Date.now()}-${idx}`;
                parent.parentNode.replaceChild(div, parent);
                try { mermaid.render(div.id + '-svg', code).then(({ svg }) => { div.innerHTML = svg; }).catch(() => {}); } catch (e) { /* diagrama inválido */ }
            });
        }

        const pie = document.createElement('div');
        pie.className = 'msg-pie';
        pie.style.cssText = 'display:flex; flex-wrap:wrap; gap:6px 12px; align-items:center; margin-top:8px; font-size:10.5px; color:var(--text-muted);';
        msgEl.appendChild(pie);

        avisos.forEach(a => {
            const d = document.createElement('div');
            d.style.cssText = 'flex-basis:100%; color:var(--accent-yellow);';
            d.textContent = a;
            pie.appendChild(d);
        });

        if (stats) {
            const partes = [];
            if (stats.generacion_tok_s) partes.push(`${stats.generacion_tok_s} tok/s`);
            partes.push(`${stats.tokens_respuesta} tokens`);
            if (stats.carga_s >= 0.5) partes.push(`carga ${stats.carga_s.toFixed(1)} s`);
            partes.push(`total ${stats.total_s.toFixed(1)} s`);
            const m = document.createElement('span');
            m.title = `Lectura del prompt: ${stats.tokens_prompt} tokens a ${stats.lectura_tok_s || '?'} tok/s · motivo de fin: ${stats.motivo_fin}`;
            m.innerHTML = `<i class="fa-solid fa-gauge-high"></i> ${partes.join(' · ')}`;
            pie.appendChild(m);
            if (stats.contexto) {
                const pct = Math.min(100, stats.contexto_usado_pct || 0);
                const color = pct > 90 ? 'var(--accent-red)' : pct > 70 ? 'var(--accent-yellow)' : 'var(--accent-green)';
                const barra = document.createElement('span');
                barra.title = `${stats.tokens_prompt + stats.tokens_respuesta} de ${stats.contexto} tokens de contexto`;
                barra.style.cssText = 'display:inline-flex; align-items:center; gap:4px;';
                barra.innerHTML = `contexto <span style="display:inline-block; width:60px; height:5px; background:rgba(255,255,255,.1); border-radius:3px; overflow:hidden;">
                    <span style="display:block; height:100%; width:${pct}%; background:${color};"></span></span> ${pct}%`;
                pie.appendChild(barra);
            }
        }

        const boton = (html, titulo, alPulsar) => {
            const b = document.createElement('button');
            b.className = 'tool-btn';
            b.style.cssText = 'font-size:10.5px; background:rgba(203,166,247,0.12); color:var(--accent-purple); border:1px solid rgba(203,166,247,.45); border-radius:4px; padding:2px 8px; cursor:pointer;';
            b.innerHTML = html;
            b.title = titulo;
            b.onclick = alPulsar;
            pie.appendChild(b);
            return b;
        };

        if (stats && stats.cortada) {
            const aviso = document.createElement('span');
            aviso.style.color = 'var(--accent-yellow)';
            aviso.innerHTML = '<i class="fa-solid fa-scissors"></i> Cortada por el límite de tokens';
            pie.appendChild(aviso);
            boton('<i class="fa-solid fa-forward"></i> Continuar', 'El modelo sigue desde donde se quedó', async () => {
                pie.remove();
                await this.pedirEventos({ ...cuerpo, continuar: fullResponse }, contentEl, fullResponse);
            });
        }

        if (logprobs && logprobs.length) {
            boton('<i class="fa-solid fa-chart-simple"></i> Ver confianza', 'Colorea cada palabra según lo seguro que estaba el modelo', (e) => {
                const activo = contentEl.dataset.confianza === '1';
                if (activo) {
                    contentEl.dataset.confianza = '';
                    contentEl.innerHTML = this.renderMarkdown(fullResponse);
                    e.currentTarget.innerHTML = '<i class="fa-solid fa-chart-simple"></i> Ver confianza';
                } else {
                    contentEl.dataset.confianza = '1';
                    contentEl.innerHTML = this.renderConfianza(logprobs);
                    e.currentTarget.innerHTML = '<i class="fa-solid fa-eye"></i> Ver normal';
                }
            });
        }

        boton('<i class="fa-solid fa-volume-high"></i> Escuchar', 'Lectura en voz alta', () => {
            if (!('speechSynthesis' in window)) { alert('Tu navegador no soporta sintetizador de voz.'); return; }
            window.speechSynthesis.cancel();
            const limpio = fullResponse.replace(/```[\s\S]*?```/g, ' Bloque de código omitido. ').replace(/[#*`_~]/g, '');
            const u = new SpeechSynthesisUtterance(limpio);
            u.lang = 'es-ES';
            window.speechSynthesis.speak(u);
        });
        this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight;
    }

    /** Cada token con un fondo según su probabilidad; al pasar el ratón, las alternativas */
    renderConfianza(logprobs) {
        const esc = (t) => String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        const html = logprobs.map(p => {
            const prob = Math.exp(p.logprob || 0);
            const fondo = prob >= 0.8 ? 'transparent' : prob >= 0.5 ? 'rgba(249,226,175,.18)' : prob >= 0.2 ? 'rgba(250,179,135,.32)' : 'rgba(243,139,168,.45)';
            const alternativas = (p.alternativas || []).map(a => `${JSON.stringify(a.token)} ${(Math.exp(a.logprob) * 100).toFixed(1)}%`).join('\n');
            return `<span style="background:${fondo}; border-radius:2px;" title="${esc(`${(prob * 100).toFixed(1)}% seguro\n${alternativas}`)}">${esc(p.token)}</span>`;
        }).join('');
        return `<div style="white-space:pre-wrap; font-family:var(--font-sans); line-height:1.6;">${html}</div>
            <div style="font-size:10px; color:var(--text-muted); margin-top:6px;">Fondo: amarillo &lt;80 %, naranja &lt;50 %, rojo &lt;20 % de seguridad. Pasa el ratón para ver las alternativas.</div>`;
    }

    explainEntireFile() {
        const fullContent = window.editorMgr ? window.editorMgr.getAIContext() : '';
        if (!fullContent || !fullContent.trim()) {
            alert('Abre un archivo o notebook primero para poder analizarlo por completo.');
            return;
        }
        const activePath = window.editorMgr.getActivePath();
        const filename = activePath ? activePath.split('/').pop() : 'archivo activo';

        this.sendMessage(
            `Realiza un ANÁLISIS INTEGRAL Y COMPLETO del archivo \`${filename}\` de principio a fin. Desglosa su estructura general, objetivo principal, funciones/clases clave, posible flujo de ejecución y recomendaciones de mejora:`,
            "explain",
            fullContent
        );
    }

    explainCodeFlow() {
        const selected = (window.editorMgr && typeof window.editorMgr.getSelectedText === 'function') ? window.editorMgr.getSelectedText() : '';
        const codeToExplain = selected || (window.editorMgr && typeof window.editorMgr.getAIContext === 'function' ? window.editorMgr.getAIContext() : '');
        this.sendMessage(
            "Explícame en DETALLE el FLUJO DE EJECUCIÓN paso a paso de este código (muestra orden de ejecución línea por línea, valores de variables y cambios de estado):",
            "explain_flow",
            codeToExplain
        );
    }

    explainSelection() {
        const selected = (window.editorMgr && typeof window.editorMgr.getSelectedText === 'function') ? window.editorMgr.getSelectedText() : '';
        if (!selected) {
            alert('Selecciona primero las líneas de código que deseas que explique.');
            return;
        }
        this.sendMessage("Explícame de forma detallada y completa qué hace este fragmento de código:", "explain", selected);
    }

    explainError(errorText) {
        const code = (window.editorMgr && typeof window.editorMgr.getAIContext === 'function') ? window.editorMgr.getAIContext() : '';
        this.sendMessage(`El programa arrojó el siguiente error al ejecutarse:\n\n${errorText}\n\nAnaliza a fondo el error, explica la causa raíz y muestra la solución completa:`, "fix", code);
    }

    async downloadSelectedModel() {
        const modelName = this.modelSelect.value || "qwen2.5-coder:7b";
        if (!confirm(`¿Deseas descargar ${modelName} en Ollama para usarlo en local?`)) {
            return;
        }

        const msgEl = this.appendMessage(`Iniciando descarga de ${modelName}... Por favor espera.`, false);
        try {
            const res = await fetch('/api/ai/pull', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ model: modelName })
            });

            if (!res.ok) {
                const errText = await res.text().catch(() => '');
                msgEl.innerHTML = `<strong>❌ Error en descarga (${res.status}):</strong> ${errText || 'Error en servidor'}`;
                return;
            }

            const reader = res.body.getReader();
            const decoder = new TextDecoder('utf-8');
            let text = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                text = decoder.decode(value, { stream: true });
                msgEl.innerHTML = `<strong>Descarga de modelo:</strong><br>${text.replace(/\n/g, '<br>')}`;
                this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight;
            }
            this.checkStatus();
        } catch (e) {
            msgEl.innerHTML = `<strong>❌ Error en descarga:</strong> ${e.message || e}`;
        }
    }
}

window.aiChatMgr = new AIChatManager();
