/**
 * NoteWindowManager - Anotador Inteligente estilo Ubuntu Text Editor
 * Soporta 2 Modos:
 * 1. Ventana Independiente: Lanza el proceso nativo de escritorio autónomo.
 * 2. Prig Note: Transforma todo el programa Prig en un Anotador IA.
 *    - Oculta la barra de herramientas del IDE (Note, Recorrido, Seguimiento, Perfil).
 *    - Muestra la lista interactiva de modelos Ollama en la barra inferior para cambiar de modelo al instante.
 *    - Incluye el botón "Prig" para retornar al entorno de desarrollo.
 */
class NoteWindowManager {
    constructor() {
        this.standaloneWindow = null;
        this.fullContainer = null;
        this.fullEditor = null;
        this.currentFilePath = null;
        this.activeModel = "qwen2.5-coder:7b";
        this.statsInterval = null;
    }

    openNoteAccordingToConfig() {
        const mode = localStorage.getItem('prig_note_launch_mode') || 'standalone';

        if (mode === 'prig_note') {
            this.enterPrigNoteView();
        } else {
            this.openIndependentDesktopWindow();
        }
    }

    // MODO PRIG NOTE: EL PROGRAMA PRIG SE CONVIERTE EN ANOTADOR
    enterPrigNoteView() {
        this.fullContainer = document.getElementById('prig-note-mode-container');
        if (!this.fullContainer) return;

        // Ocultar la barra de menú superior (Archivo, Configuración, etc.) y la barra de herramientas
        const menuBar = document.querySelector('.ide-menu-bar');
        if (menuBar) menuBar.style.display = 'none';

        const toolbar = document.querySelector('.ide-toolbar');
        if (toolbar) toolbar.style.display = 'none';

        this.fullContainer.style.display = 'flex';
        this.initFullEditor();
        this.loadAvailableModelsIntoSelect();
        this.startHardwareStatsMonitoring();
    }

    // SALIR DE PRIG NOTE Y VOLVER AL IDE PRIG
    exitPrigNoteView() {
        if (this.fullContainer) {
            this.fullContainer.style.display = 'none';
        }

        // Restaurar la barra de menú superior y la barra de herramientas del IDE Prig
        const menuBar = document.querySelector('.ide-menu-bar');
        if (menuBar) menuBar.style.display = 'flex';

        const toolbar = document.querySelector('.ide-toolbar');
        if (toolbar) toolbar.style.display = 'flex';
    }

    async loadAvailableModelsIntoSelect(preferredModel = null) {
        const selectEl = document.getElementById('prig-note-model-select');
        if (!selectEl) return;

        try {
            const res = await fetch('/api/ai/models');
            if (res.ok) {
                const data = await res.json();
                const models = data.models || [];
                if (models.length > 0) {
                    if (preferredModel && models.includes(preferredModel)) {
                        this.activeModel = preferredModel;
                    }
                    selectEl.innerHTML = '';
                    models.forEach(m => {
                        const opt = document.createElement('option');
                        opt.value = m;
                        opt.textContent = m;
                        opt.style.backgroundColor = '#1e1e2e';
                        opt.style.color = '#cdd6f4';
                        if (m === this.activeModel) opt.selected = true;
                        selectEl.appendChild(opt);
                    });
                }
            }
        } catch (e) {}
    }

    onModelChange(modelName) {
        this.activeModel = modelName;
        console.log("🤖 Modelo de Ollama seleccionado en Prig Note:", modelName);
    }

    initFullEditor() {
        if (typeof monaco === 'undefined' || this.fullEditor) {
            if (this.fullEditor) this.fullEditor.layout();
            return;
        }

        const container = document.getElementById('prig-note-monaco-full');
        if (!container) return;

        const savedContent = localStorage.getItem('prig_note_saved_content') || 
            '# Prig Note - Anotador Inteligente IA\n# Escribe /ex: tema y presiona Enter para pedir una explicación en ~500 palabras.\n# Ejemplo:\n# /ex: algoritmos de ordenamiento\n\n';

        this.currentFilePath = localStorage.getItem('prig_note_active_path') || null;

        this.fullEditor = monaco.editor.create(container, {
            value: savedContent,
            language: 'python',
            theme: 'prig-dark',
            automaticLayout: true,
            fontSize: 14,
            fontFamily: "'Fira Code', 'Ubuntu Mono', monospace",
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            smoothScrolling: true,
            lineNumbers: 'on',
            renderLineHighlight: 'all',
            folding: true,
            foldingStrategy: 'auto',
            showFoldingControls: 'always',
            suggest: { showWords: true }
        });

        // Guardado automático continuo
        this.fullEditor.onDidChangeModelContent(() => {
            const content = this.fullEditor.getValue();
            localStorage.setItem('prig_note_saved_content', content);
            if (this.currentFilePath) {
                localStorage.setItem('prig_note_active_path', this.currentFilePath);
            }
        });

        // Posición de Cursor
        this.fullEditor.onDidChangeCursorPosition((e) => {
            const pos = e.position;
            const lnColEl = document.getElementById('prig-note-stat-lncol');
            if (lnColEl) lnColEl.innerText = `Ln ${pos.lineNumber}, Col ${pos.column}`;
        });

        // PARSER DE COMANDO /ex: <tema> AL PRESIONAR ENTER EN PRIG NOTE
        this.fullEditor.addCommand(monaco.KeyCode.Enter, async () => {
            const position = this.fullEditor.getPosition();
            const lineContent = this.fullEditor.getModel().getLineContent(position.lineNumber);
            const match = lineContent.match(/^\/ex:\s*(.+)/i);

            if (match) {
                const topic = match[1].trim();
                const lineNumber = position.lineNumber;
                
                const loadingTag = `\n## 📚 Explicación: ${topic}\n*🤖 Generando explicación pedagógica en ~500 palabras...*\n\n`;
                this.fullEditor.executeEdits("ex-cmd", [{
                    range: new monaco.Range(lineNumber, 1, lineNumber, lineContent.length + 1),
                    text: loadingTag
                }]);

                try {
                    const res = await fetch('/api/note/explain', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ topic: topic, model: this.activeModel })
                    });

                    if (res.ok) {
                        const reader = res.body.getReader();
                        const decoder = new TextDecoder("utf-8");
                        let fullExplanation = "";

                        while (true) {
                            const { done, value } = await reader.read();
                            if (done) break;
                            fullExplanation += decoder.decode(value, { stream: true });
                        }

                        const currentVal = this.fullEditor.getValue();
                        const updatedVal = currentVal.replace(
                            `*🤖 Generando explicación pedagógica en ~500 palabras...*`,
                            fullExplanation.trim()
                        );
                        this.fullEditor.setValue(updatedVal);
                    }
                } catch (e) {
                    alert("Error al solicitar explicación: " + e.message);
                }
            } else {
                this.fullEditor.trigger('keyboard', 'type', { text: '\n' });
            }
        });

        // Autocompletado IA en Texto Fantasma con TAB
        if (monaco.languages.registerInlineCompletionsProvider) {
            monaco.languages.registerInlineCompletionsProvider('python', {
                provideInlineCompletions: async (model, position, context, token) => {
                    const lineContent = model.getLineContent(position.lineNumber);
                    if (!lineContent.trim() || lineContent.trim().length < 2) {
                        return { items: [] };
                    }

                    const prefix = model.getValueInRange({
                        startLineNumber: Math.max(1, position.lineNumber - 10),
                        startColumn: 1,
                        endLineNumber: position.lineNumber,
                        endColumn: position.column
                    });

                    try {
                        const res = await fetch('/api/ai/inline-complete', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                code_prefix: prefix,
                                model: this.activeModel
                            })
                        });
                        if (!res.ok) return { items: [] };
                        const data = await res.json();
                        if (data.completion) {
                            return {
                                items: [{
                                    insertText: data.completion,
                                    range: new monaco.Range(position.lineNumber, position.column, position.lineNumber, position.column + data.completion.length)
                                }]
                            };
                        }
                    } catch (e) {}
                    return { items: [] };
                },
                freeInlineCompletions: () => {}
            });
        }
    }

    async openIndependentDesktopWindow() {
        try {
            const res = await fetch('/api/note/open-standalone', { method: 'POST' });
            if (res.ok) {
                const data = await res.json();
                if (data.status === 'success') {
                    localStorage.setItem('prig_note_was_open', 'true');
                    return;
                }
            }
        } catch (e) {
            console.warn("⚠️ No se pudo lanzar proceso nativo, abriendo Prig Note...");
        }

        this.enterPrigNoteView();
    }

    newNote() {
        if (this.fullEditor) {
            this.fullEditor.setValue('# Documento sin título\n\n');
            this.currentFilePath = null;
            localStorage.removeItem('prig_note_active_path');
            const titleEl = document.getElementById('prig-note-full-title');
            if (titleEl) titleEl.innerText = 'Documento sin título 1';
        }
    }

    async openWorkspaceFilePicker() {
        try {
            const res = await fetch('/api/tree');
            if (!res.ok) throw new Error("Error al leer árbol de archivos");
            const tree = await res.json();
            
            const pickerModal = document.getElementById('modal-note-picker');
            const pickerList = document.getElementById('note-picker-list');
            if (!pickerModal || !pickerList) return;

            const renderItems = (items) => {
                let html = '';
                items.forEach(item => {
                    if (item.type === 'directory') {
                        if (item.children && item.children.length > 0) {
                            html += renderItems(item.children);
                        }
                    } else {
                        html += `
                            <div class="note-picker-item" onclick="window.noteWindowMgr.loadWorkspaceFile('${item.path}')" style="padding: 8px 12px; border-bottom: 1px solid var(--border-color); cursor: pointer; display: flex; align-items: center; justify-content: space-between; font-size: 12px;">
                                <span><i class="fa-regular fa-file-code" style="color: var(--accent-blue);"></i> ${item.name}</span>
                                <span style="color: var(--text-muted); font-size: 10px;">${item.path}</span>
                            </div>
                        `;
                    }
                });
                return html;
            };

            pickerList.innerHTML = renderItems(tree);
            pickerModal.style.display = 'flex';
        } catch (err) {
            alert("Error al cargar archivos del proyecto Prig: " + err.message);
        }
    }

    async loadWorkspaceFile(path) {
        try {
            const res = await fetch(`/api/file?path=${encodeURIComponent(path)}`);
            if (!res.ok) throw new Error("Error leyendo el archivo");
            const data = await res.json();
            if (this.fullEditor) {
                this.fullEditor.setValue(data.content || '');
                this.currentFilePath = path;
                localStorage.setItem('prig_note_active_path', path);
                const fileName = path.split('/').pop();
                const titleEl = document.getElementById('prig-note-full-title');
                if (titleEl) titleEl.innerText = fileName;
            }
            const pickerModal = document.getElementById('modal-note-picker');
            if (pickerModal) pickerModal.style.display = 'none';
        } catch (err) {
            alert("Error leyendo archivo: " + err.message);
        }
    }

    async saveToWorkspaceFile() {
        if (!this.fullEditor) return;
        const content = this.fullEditor.getValue();
        
        let path = this.currentFilePath;
        if (!path) {
            path = prompt("Ingresa el nombre o ruta dentro de Prig IDE para guardar (Ej: mi_nota.py):", "mi_nota.py");
            if (!path) return;
        }

        try {
            const res = await fetch('/api/file', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: path, content: content })
            });

            if (!res.ok) throw new Error("Error al guardar archivo en el proyecto");
            this.currentFilePath = path;
            localStorage.setItem('prig_note_active_path', path);
            const fileName = path.split('/').pop();
            const titleEl = document.getElementById('prig-note-full-title');
            if (titleEl) titleEl.innerText = fileName;
            alert(`✅ Nota guardada exitosamente en '${path}' dentro del proyecto.`);
            if (window.fileTreeMgr) window.fileTreeMgr.refreshTree();
        } catch (err) {
            alert("Error guardando en proyecto: " + err.message);
        }
    }

    async startHardwareStatsMonitoring() {
        const fetchStats = async () => {
            try {
                const resStats = await fetch('/api/system/stats');
                if (resStats.ok) {
                    const stats = await resStats.json();
                    const cpuEl = document.getElementById('prig-note-stat-cpu');
                    const ramEl = document.getElementById('prig-note-stat-ram');
                    const gpuEl = document.getElementById('prig-note-stat-gpu');

                    if (cpuEl) cpuEl.innerText = `CPU: ${stats.cpu_pct || 0}%`;
                    if (ramEl) ramEl.innerText = `RAM: ${stats.ram_used_gb || 0}GB/${stats.ram_total_gb || 0}GB (${stats.ram_pct || 0}%)`;
                    if (gpuEl) {
                        if (stats.gpu_name && stats.gpu_name !== 'N/A') {
                            gpuEl.innerText = `GPU: ${stats.gpu_used_gb || 0}GB/${stats.gpu_total_gb || 0}GB`;
                        } else {
                            gpuEl.innerText = `GPU: N/A`;
                        }
                    }
                }
            } catch (e) {}
        };

        fetchStats();
        if (!this.statsInterval) {
            this.statsInterval = setInterval(fetchStats, 3500);
        }
    }
}

// Global instance
window.noteWindowMgr = new NoteWindowManager();

window.openNoteWindow = function() {
    if (window.noteWindowMgr) {
        window.noteWindowMgr.openNoteAccordingToConfig();
    } else {
        window.noteWindowMgr = new NoteWindowManager();
        window.noteWindowMgr.openNoteAccordingToConfig();
    }
};
