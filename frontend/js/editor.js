class EditorManager {
    constructor() {
        this.editor = null;
        this.openTabs = new Map(); // path -> { name, content, model, isNotebook, notebookData }
        this.activePath = null;
        this.initMonaco();
    }

    initMonaco() {
        require.config({ paths: { 'vs': 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs' } });
        require(['vs/editor/editor.main'], () => {
            monaco.editor.defineTheme('prig-dark', {
                base: 'vs-dark',
                inherit: true,
                rules: [],
                colors: {
                    'editor.background': '#1e1e1e',
                    'editor.lineHighlightBackground': '#2a2d2e',
                    'editorLineNumber.foreground': '#858585',
                    'editorLineNumber.activeForeground': '#cccccc',
                    'editorIndentGuide.background': '#333333'
                }
            });

            this.editor = monaco.editor.create(document.getElementById('monaco-editor-container'), {
                value: '',
                language: 'python',
                theme: 'prig-dark',
                automaticLayout: true,
                fontSize: 14,
                fontFamily: "'Fira Code', monospace",
                minimap: { enabled: false },
                scrollBeyondLastLine: false,
                smoothScrolling: true
            });

            window.notebookMgr.init(document.getElementById('notebook-view-container'));
            this.pintarVacio();
            // Opciones de IDE (vista, problemas, navegación…) se enganchan aquí
            window.dispatchEvent(new CustomEvent('prig:editor-creado', { detail: { editor: this.editor, principal: true } }));

            // Keyboard shortcut Ctrl+S
            this.editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
                if (window.app) window.app.saveCurrentFile();
            });

            // Keyboard shortcut Ctrl+Enter: si la línea contiene "Prig//: ", ejecuta el prompt en línea
            this.editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => {
                const position = this.editor.getPosition();
                if (position) {
                    let targetLine = position.lineNumber;
                    let lineContent = this.editor.getModel()?.getLineContent(targetLine) || '';
                    let match = lineContent.match(/Prig\/\/:\s*(.*)$/i);

                    // Si la línea actual está vacía o no tiene prompt, pero la anterior sí (el usuario pulsó Enter después de escribirlo)
                    if (!match && targetLine > 1) {
                        const prevContent = this.editor.getModel()?.getLineContent(targetLine - 1) || '';
                        const prevMatch = prevContent.match(/Prig\/\/:\s*(.*)$/i);
                        if (prevMatch) {
                            targetLine = targetLine - 1;
                            lineContent = prevContent;
                            match = prevMatch;
                        }
                    }

                    if (match) {
                        const promptText = match[1].replace(/(-->|\*\/)\s*$/, '').trim();
                        this.executeInlinePrompt(targetLine, promptText);
                        return;
                    }
                }
                if (window.app) window.app.runCode();
            });

            // Registrar CodeLens interactivo para prompts en línea "Prig//: "
            const supportedLangs = [
                'python', 'javascript', 'typescript', 'html', 'css', 'scss', 'less', 'json',
                'markdown', 'shell', 'c', 'cpp', 'java', 'go', 'rust', 'ruby', 'php',
                'sql', 'yaml', 'xml', 'ini', 'r', 'julia', 'lua', 'kotlin', 'swift',
                'csharp', 'dockerfile', 'plaintext'
            ];
            const codeLensProvider = {
                provideCodeLenses: (model) => {
                    const lenses = [];
                    const lines = model.getLinesContent();
                    for (let i = 0; i < lines.length; i++) {
                        const line = lines[i];
                        const match = line.match(/Prig\/\/:\s*(.*)$/i);
                        if (match) {
                            const promptText = match[1].replace(/(-->|\*\/)\s*$/, '').trim();
                            const lineNumber = i + 1;
                            lenses.push({
                                range: new monaco.Range(lineNumber, 1, lineNumber, line.length + 1),
                                id: `prig-lens-${lineNumber}`,
                                command: {
                                    id: 'prig.executeInlinePrompt',
                                    title: promptText ? '✨ Prig: Generar código (Ctrl+Enter)' : '✨ Prig: Escribe una instrucción y presiona Ctrl+Enter',
                                    arguments: [lineNumber, promptText]
                                }
                            });
                        }
                    }
                    return { lenses, dispose: () => {} };
                },
                resolveCodeLens: (model, codeLens) => codeLens
            };
            supportedLangs.forEach(lang => {
                try {
                    monaco.languages.registerCodeLensProvider(lang, codeLensProvider);
                } catch (e) {}
            });

            try {
                monaco.editor.registerCommand('prig.executeInlinePrompt', (accessor, lineNumber, promptText) => {
                    this.executeInlinePrompt(lineNumber, promptText);
                });
            } catch (e) {}

            // Registrar Autocompletado de Código (Ghost Text IA)
            if (monaco.languages.registerInlineCompletionsProvider) {
                monaco.languages.registerInlineCompletionsProvider('python', {
                    provideInlineCompletions: async (model, position, context, token) => {
                        const lineContent = model.getLineContent(position.lineNumber);
                        if (!lineContent.trim() || lineContent.trim().length < 3) {
                            return { items: [] };
                        }

                        const prefix = model.getValueInRange({
                            startLineNumber: Math.max(1, position.lineNumber - 60),
                            startColumn: 1,
                            endLineNumber: position.lineNumber,
                            endColumn: position.column
                        });
                        // Lo que hay después del cursor: con él, un modelo con "insert"
                        // rellena el medio en vez de adivinar cómo sigue el archivo
                        const ultima = model.getLineCount();
                        const suffix = model.getValueInRange({
                            startLineNumber: position.lineNumber,
                            startColumn: position.column,
                            endLineNumber: Math.min(ultima, position.lineNumber + 40),
                            endColumn: model.getLineMaxColumn(Math.min(ultima, position.lineNumber + 40))
                        });

                        try {
                            const res = await fetch('/api/ai/inline-complete', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ code_prefix: prefix, code_suffix: suffix })
                            });
                            if (!res.ok) return { items: [] };
                            const data = await res.json();
                            if (data.completion) {
                                return {
                                    items: [{
                                        insertText: data.completion,
                                        range: new monaco.Range(position.lineNumber, position.column, position.lineNumber, position.column)
                                    }]
                                };
                            }
                        } catch (e) {}
                        return { items: [] };
                    },
                    freeInlineCompletions: () => {}
                });
            }
        });
    }

    /**
     * Abre un archivo a partir de su ruta, pidiendo el contenido al backend.
     * Existe porque varios sitios llamaban a openFile(path) con un solo argumento,
     * lo que reventaba con TypeError al no recibir name ni content.
     */
    async openFileByPath(path, name = null) {
        if (!path) return false;
        try {
            const res = await fetch(`/api/file?path=${encodeURIComponent(path)}`);
            if (!res.ok) {
                let detail = `HTTP ${res.status}`;
                try { detail = (await res.json()).detail || detail; } catch (e) {}
                throw new Error(detail);
            }
            const data = await res.json();
            if (data.content === undefined) throw new Error('El archivo no devolvió contenido.');

            const fileName = name || data.name || path.split('/').pop();
            this.openFile(data.path || path, fileName, data.content, data.notebook_data);
            return true;
        } catch (e) {
            console.error('Error abriendo archivo:', path, e);
            if (window.terminalMgr) {
                window.terminalMgr.appendLine(`[No se pudo abrir ${path}: ${e.message}]`, 'stderr');
            }
            return false;
        }
    }

    openFile(path, name, content, notebookData = null) {
        if (!this.editor) return;

        const isNotebook = name.endsWith('.ipynb');
        const ext = name.split('.').pop().toLowerCase();
        const langMap = {
            'py': 'python', 'pyw': 'python', 'js': 'javascript', 'mjs': 'javascript', 'cjs': 'javascript',
            'ts': 'typescript', 'tsx': 'typescript', 'jsx': 'javascript', 'html': 'html', 'htm': 'html',
            'css': 'css', 'scss': 'scss', 'less': 'less', 'json': 'json', 'md': 'markdown',
            'sh': 'shell', 'bash': 'shell', 'zsh': 'shell', 'c': 'c', 'h': 'c', 'cpp': 'cpp', 'hpp': 'cpp',
            'cc': 'cpp', 'java': 'java', 'go': 'go', 'rs': 'rust', 'rb': 'ruby', 'php': 'php',
            'sql': 'sql', 'yaml': 'yaml', 'yml': 'yaml', 'xml': 'xml', 'svg': 'xml', 'toml': 'ini',
            'ini': 'ini', 'cfg': 'ini', 'r': 'r', 'jl': 'julia', 'lua': 'lua', 'kt': 'kotlin',
            'swift': 'swift', 'cs': 'csharp', 'dockerfile': 'dockerfile', 'tex': 'latex', 'ipynb': 'python'
        };
        const lang = langMap[ext] || 'plaintext';

        if (!this.openTabs.has(path)) {
            const model = monaco.editor.createModel(content, lang);
            // savedContent es la referencia contra la que se decide si hay cambios
            // sin guardar. Sin esto, cerrar una pestaña destruía el trabajo en silencio.
            const tab = { name, path, model, isNotebook, notebookData, savedContent: content };
            this.openTabs.set(path, tab);
            // tab.path y no `path`: al renombrar la pestaña cambia de clave
            model.onDidChangeContent(() => {
                this.checkAutoComment(tab.path);
                this.onContentChanged(tab.path);
            });
        } else {
            // La pestaña ya existía: refrescar con lo que hay ahora en disco en vez de
            // seguir mostrando la copia antigua.
            const tab = this.openTabs.get(path);
            if (tab.model.getValue() !== content) {
                tab.model.setValue(content);
            }
            tab.savedContent = content;
            tab.notebookData = notebookData;
        }

        this.setActiveTab(path);
        this.saveSessionState();
        // Abrir un archivo trae el editor al frente (con Inicio u otra herramienta delante no
        // se veía nada). Al restaurar la sesión del arranque no: ahí manda el Inicio.
        if (!this._restaurando && window.workArea && window.workArea.activa !== 'editor') window.workArea.activar('editor');
        window.dispatchEvent(new CustomEvent('prig:archivo-abierto', { detail: { path } }));
    }

    setActiveTab(path) {
        const tabData = this.openTabs.get(path);
        if (!tabData) return;

        this.activePath = path;
        this.editor.setModel(tabData.model);

        const monacoContainer = document.getElementById('monaco-editor-container');
        const notebookContainer = document.getElementById('notebook-view-container');
        const viewModeBar = document.getElementById('view-mode-bar');

        if (tabData.isNotebook && tabData.notebookData) {
            viewModeBar.style.display = 'flex';
            monacoContainer.style.display = 'none';
            notebookContainer.style.display = 'flex';
            window.notebookMgr.renderNotebook(tabData.notebookData);
        } else {
            viewModeBar.style.display = 'none';
            monacoContainer.style.display = 'block';
            notebookContainer.style.display = 'none';
        }

        this.renderTabs();
        this.saveSessionState();
        window.dispatchEvent(new CustomEvent('prig:pestana-activa', { detail: { path } }));
    }

    showSourceEditor() {
        document.getElementById('monaco-editor-container').style.display = 'block';
        document.getElementById('notebook-view-container').style.display = 'none';
        document.getElementById('btn-view-notebook').className = 'view-toggle-btn';
        document.getElementById('btn-view-source').className = 'view-toggle-btn active';
    }

    showNotebookView() {
        const tabData = this.openTabs.get(this.activePath);
        if (tabData && tabData.notebookData) {
            document.getElementById('monaco-editor-container').style.display = 'none';
            document.getElementById('notebook-view-container').style.display = 'flex';
            document.getElementById('btn-view-notebook').className = 'view-toggle-btn active';
            document.getElementById('btn-view-source').className = 'view-toggle-btn';
        }
    }

    closeTab(path, event, forzar = false) {
        if (event) event.stopPropagation();
        const tabData = this.openTabs.get(path);

        // Antes se destruía el modelo directamente: cerrar una pestaña con cambios
        // sin guardar borraba el trabajo sin una sola pregunta. `forzar` solo lo usan
        // "Guardar como" (el contenido ya está en el archivo nuevo) y "Eliminar".
        if (tabData && !forzar && this.isDirty(path)) {
            const nombre = tabData.name || path;
            if (!confirm(`"${nombre}" tiene cambios sin guardar.\n\n¿Cerrar de todos modos y perderlos?`)) {
                return false;
            }
        }

        if (tabData) {
            // Si una columna dividida muestra este archivo, se cierra antes de
            // destruir su modelo (un editor con el modelo destruido se rompe)
            if (window.workArea && window.workArea.grupos) {
                window.workArea.grupos.filter(g => g.path === path).forEach(g => window.workArea.cerrarGrupo(g.id));
            }
            tabData.model.dispose();
            this.openTabs.delete(path);
            if (this._lastDirty) delete this._lastDirty[path];
            window.dispatchEvent(new CustomEvent('prig:pestana-cerrada', { detail: { path } }));
        }

        if (this.activePath === path) {
            const keys = Array.from(this.openTabs.keys());
            if (keys.length > 0) {
                this.setActiveTab(keys[keys.length - 1]);
            } else {
                this.activePath = null;
                this.editor.setModel(monaco.editor.createModel('', 'plaintext'));
                document.getElementById('view-mode-bar').style.display = 'none';
                document.getElementById('monaco-editor-container').style.display = 'block';
                document.getElementById('notebook-view-container').style.display = 'none';
            }
        }
        this.renderTabs();
        this.saveSessionState();
        return true;
    }

    /** Sin pestañas se ve «No hay ningún archivo abierto» en lugar de un editor vacío */
    pintarVacio() {
        const vacio = document.getElementById('editor-vacio');
        if (!vacio) return;
        const sinArchivos = this.openTabs.size === 0;
        vacio.hidden = !sinArchivos;
        const monacoEl = document.getElementById('monaco-editor-container');
        const tabs = document.getElementById('editor-tabs');
        if (sinArchivos) {
            monacoEl.style.display = 'none';
            document.getElementById('notebook-view-container').style.display = 'none';
            document.getElementById('view-mode-bar').style.display = 'none';
        }
        if (tabs) tabs.hidden = sinArchivos;
        if (!vacio.dataset.conectado) {
            vacio.dataset.conectado = '1';
            vacio.addEventListener('click', (e) => {
                const b = e.target.closest('[data-cmd]');
                if (b && window.PrigCommands) window.PrigCommands.ejecutar(b.dataset.cmd);
            });
        }
    }

    renderTabs() {
        this.pintarVacio();
        const container = document.getElementById('editor-tabs');
        container.innerHTML = '';
        this.openTabs.forEach((tab, path) => {
            const tabEl = document.createElement('div');
            tabEl.className = `tab-item ${path === this.activePath ? 'active' : ''}`;
            tabEl.dataset.path = path;
            tabEl.title = path;
            const icon = tab.isNotebook ? '<i class="fa-solid fa-book-bookmark" style="color:var(--accent-yellow); font-size:11px;"></i>' : '';
            const dirty = this.isDirty(path);
            tabEl.innerHTML = `
                ${icon}
                <span class="tab-name"></span>
                <span class="tab-dirty" title="Cambios sin guardar"${dirty ? '' : ' hidden'}>●</span>
                <i class="fa-solid fa-xmark tab-close"></i>
            `;
            // textContent en vez de interpolar: un nombre de archivo con < o comillas
            // rompía el HTML (y el onclick inline con la ruta).
            tabEl.querySelector('.tab-name').textContent = tab.name;
            tabEl.querySelector('.tab-close').onclick = (event) => this.closeTab(path, event);
            tabEl.onclick = () => this.setActiveTab(path);
            // Clic central cierra, como en cualquier editor
            tabEl.onauxclick = (event) => { if (event.button === 1) this.closeTab(path, event); };
            container.appendChild(tabEl);
        });
    }

    /** ¿La pestaña tiene cambios sin guardar? */
    isDirty(path) {
        const tab = this.openTabs.get(path);
        if (!tab || tab.savedContent === undefined) return false;
        return tab.model.getValue() !== tab.savedContent;
    }

    hasUnsavedChanges() {
        return Array.from(this.openTabs.keys()).some(p => this.isDirty(p));
    }

    /** Marca la pestaña como guardada tras una escritura confirmada por el backend */
    markSaved(path, content = null) {
        const tab = this.openTabs.get(path);
        if (!tab) return;
        tab.savedContent = content !== null ? content : tab.model.getValue();
        this.renderTabs();
    }

    /** Una pestaña pasa a apuntar a otra ruta (renombrar o mover el archivo) */
    renombrarPestana(anterior, nueva) {
        const tab = this.openTabs.get(anterior);
        if (!tab || anterior === nueva) return;
        const entradas = Array.from(this.openTabs.entries()).map(([p, t]) => p === anterior ? [nueva, t] : [p, t]);
        this.openTabs = new Map(entradas);
        tab.path = nueva;
        tab.name = nueva.split('/').pop();
        if (this._lastDirty && anterior in this._lastDirty) {
            this._lastDirty[nueva] = this._lastDirty[anterior];
            delete this._lastDirty[anterior];
        }
        if (this.activePath === anterior) this.activePath = nueva;
        if (window.workArea && window.workArea.grupos) {
            window.workArea.grupos.filter(g => g.path === anterior).forEach(g => {
                g.path = nueva;
                const n = g.el && g.el.querySelector('.grupo-nombre');
                if (n) n.textContent = tab.name;
            });
        }
        this.renderTabs();
        this.saveSessionState();
        window.dispatchEvent(new CustomEvent('prig:pestana-renombrada', { detail: { anterior, nueva } }));
    }

    /** Repinta las pestañas solo cuando cambia el estado modificado/guardado */
    onContentChanged(path) {
        window.dispatchEvent(new CustomEvent('prig:contenido-cambiado', { detail: { path } }));
        const dirty = this.isDirty(path);
        if (this._lastDirty === undefined) this._lastDirty = {};
        if (this._lastDirty[path] !== dirty) {
            this._lastDirty[path] = dirty;
            this.renderTabs();
        }
    }

    /**
     * Contenido REAL del archivo, apto para escribirse en disco.
     * Para un .ipynb devuelve el JSON nbformat intacto: nunca el resumen por celdas,
     * porque guardarlo destruiría el cuaderno.
     */
    getContent() {
        return this.editor ? this.editor.getValue() : '';
    }

    /**
     * Contenido legible para enviar como contexto a la IA. En los cuadernos se
     * aplana a celdas numeradas porque el JSON crudo desperdicia la ventana de contexto.
     */
    getAIContext() {
        const activeTab = this.openTabs.get(this.activePath);
        if (activeTab && activeTab.isNotebook && window.notebookMgr && window.notebookMgr.cellsData && window.notebookMgr.cellsData.length > 0) {
            return window.notebookMgr.cellsData.map((cell, idx) => {
                const cType = (cell.type || cell.cell_type || 'code').toUpperCase();
                return `--- [CELDA ${idx + 1} - ${cType}] ---\n${cell.source}`;
            }).join('\n\n');
        }
        return this.getContent();
    }

    getSelectedText() {
        const activeTab = this.openTabs.get(this.activePath);
        if (!activeTab || !activeTab.isNotebook) {
            if (this.editor) {
                const selection = this.editor.getSelection();
                if (selection && !selection.isEmpty()) {
                    return this.editor.getModel().getValueInRange(selection);
                }
            }
        }
        return this.getAIContext();
    }

    getActivePath() {
        return this.activePath;
    }

    /** Obtiene la sintaxis de comentarios según el lenguaje activo */
    getCommentSyntax(lang) {
        switch (lang) {
            case 'python':
            case 'shell':
            case 'yaml':
            case 'dockerfile':
            case 'r':
            case 'ruby':
            case 'ini':
                return { prefix: '# ', suffix: '' };
            case 'html':
            case 'xml':
                return { prefix: '<!-- ', suffix: ' -->' };
            case 'css':
            case 'scss':
            case 'less':
                return { prefix: '/* ', suffix: ' */' };
            case 'sql':
            case 'lua':
                return { prefix: '-- ', suffix: '' };
            default:
                // javascript, typescript, c, cpp, csharp, java, go, rust, php, kotlin, swift, plaintext, etc.
                return { prefix: '// ', suffix: '' };
        }
    }

    /**
     * Detecta si el usuario escribe "Prig//:" y lo convierte automáticamente en un comentario
     * en el lenguaje que corresponda, respetando la posición del cursor para continuar escribiendo.
     */
    checkAutoComment(path) {
        if (this._isAutoCommenting || !this.editor) return;
        const tab = this.openTabs.get(path);
        if (!tab || !tab.model) return;
        const model = tab.model;
        const position = this.editor.getPosition();
        if (!position) return;

        const lineNumber = position.lineNumber;
        const lineContent = model.getLineContent(lineNumber);

        // Buscar "Prig//:" en la línea
        const idx = lineContent.search(/Prig\/\/:/i);
        if (idx === -1) return;

        const before = lineContent.substring(0, idx);
        // Si antes de Prig//: ya existe un delimitador de comentario, no intervenir
        if (before.includes('//') || before.includes('#') || before.includes('/*') || before.includes('<!--') || before.includes('--')) {
            return;
        }

        const lang = model.getLanguageId();
        const comment = this.getCommentSyntax(lang);

        if (before.trim().startsWith(comment.prefix.trim())) {
            return;
        }

        this._isAutoCommenting = true;
        try {
            const indent = (lineContent.match(/^(\s*)/) || [''])[0];
            const restOfLine = lineContent.substring(indent.length);
            let newLine = `${indent}${comment.prefix}${restOfLine}`;
            if (comment.suffix && !newLine.includes(comment.suffix.trim())) {
                newLine = `${newLine}${comment.suffix}`;
            }

            const maxCol = model.getLineMaxColumn(lineNumber);
            this.editor.executeEdits('prig-autocomment', [{
                range: new monaco.Range(lineNumber, 1, lineNumber, maxCol),
                text: newLine,
                forceMoveMarkers: true
            }]);

            const addedLen = comment.prefix.length;
            this.editor.setPosition({
                lineNumber: lineNumber,
                column: Math.min(newLine.length + 1, position.column + addedLen)
            });
        } finally {
            this._isAutoCommenting = false;
        }
    }

    /**
     * Ejecuta una instrucción de prompt en línea "Prig//: <instrucción>"
     * y genera el código correspondiente directamente en el archivo.
     */
    async executeInlinePrompt(lineNumber, promptText = null) {
        if (!this.editor) return;
        const model = this.editor.getModel();
        if (!model) return;

        const lineContent = model.getLineContent(lineNumber);
        if (!promptText) {
            const match = lineContent.match(/Prig\/\/:\s*(.*)$/i);
            promptText = match ? match[1].replace(/(-->|\*\/)\s*$/, '').trim() : '';
        }

        if (!promptText) {
            if (window.terminalMgr) {
                window.terminalMgr.appendLine('[Prig IA] Escribe una instrucción después de "Prig//: " para generar código (ejemplo: Prig//: función para ordenar lista).', 'stderr');
            }
            return;
        }

        const lang = model.getLanguageId();
        const comment = this.getCommentSyntax(lang);
        const indent = (lineContent.match(/^(\s*)/) || [''])[0];

        // 1. Capturar contenido completo ANTES de insertar el marcador de carga
        const fullContent = model.getValue();

        // 2. Extraer código de contexto previo y posterior
        const prefix = model.getValueInRange({
            startLineNumber: 1,
            startColumn: 1,
            endLineNumber: lineNumber,
            endColumn: lineContent.length + 1
        });

        const lastLine = model.getLineCount();
        let suffix = "";
        if (lineNumber < lastLine) {
            suffix = model.getValueInRange({
                startLineNumber: lineNumber + 1,
                startColumn: 1,
                endLineNumber: lastLine,
                endColumn: model.getLineMaxColumn(lastLine)
            });
        }

        // 3. Insertar marcador de carga temporal justo debajo de la línea del prompt
        const placeholderText = `${indent}${comment.prefix}[⏳ Prig IA generando código...]${comment.suffix}`;
        const insertRange = new monaco.Range(lineNumber + 1, 1, lineNumber + 1, 1);

        this.editor.executeEdits('prig-inline', [{
            range: insertRange,
            text: placeholderText + '\n',
            forceMoveMarkers: true
        }]);

        const placeholderLine = lineNumber + 1;

        const modelSelect = document.getElementById('model-select') || document.getElementById('ai-model-select');
        // Prig//: escribe código: el modelo elegido para «Código» en Configuración, o el del chat
        const selectedModel = window.PrigModelos
            ? window.PrigModelos.para('codigo', modelSelect ? modelSelect.value : null)
            : (modelSelect ? modelSelect.value : null);

        try {
            const res = await fetch('/api/ai/inline-prompt', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    file_path: this.activePath || 'archivo',
                    file_content: fullContent,
                    line_number: lineNumber,
                    language: lang,
                    prompt: promptText,
                    prefix_code: prefix,
                    suffix_code: suffix,
                    model: selectedModel
                })
            });

            if (!res.ok) {
                let detailMsg = `Error HTTP ${res.status}`;
                try {
                    const errData = await res.json();
                    if (typeof errData.detail === 'string') {
                        detailMsg = errData.detail;
                    } else if (Array.isArray(errData.detail)) {
                        detailMsg = errData.detail.map(d => d.msg || JSON.stringify(d)).join(', ');
                    } else if (errData.detail) {
                        detailMsg = JSON.stringify(errData.detail);
                    }
                } catch (e) {}
                throw new Error(detailMsg);
            }

            const data = await res.json();
            const generatedCode = (data.code || '').trimEnd();

            // Reemplazar el marcador por el código generado
            const replaceRange = new monaco.Range(
                placeholderLine,
                1,
                placeholderLine,
                model.getLineMaxColumn(placeholderLine)
            );

            this.editor.executeEdits('prig-inline', [{
                range: replaceRange,
                text: generatedCode || `${indent}${comment.prefix}[No se generó código]${comment.suffix}`,
                forceMoveMarkers: true
            }]);

            if (window.terminalMgr) {
                window.terminalMgr.appendLine(`[Prig IA] Código generado para: "${promptText}"`, 'stdout');
            }
        } catch (err) {
            console.error('Error generando código en línea:', err);
            const replaceRange = new monaco.Range(
                placeholderLine,
                1,
                placeholderLine,
                model.getLineMaxColumn(placeholderLine)
            );
            this.editor.executeEdits('prig-inline', [{
                range: replaceRange,
                text: `${indent}${comment.prefix}[❌ Error Prig IA: ${err.message}]${comment.suffix}`,
                forceMoveMarkers: true
            }]);
            if (window.terminalMgr) {
                window.terminalMgr.appendLine(`[Prig IA Error] ${err.message}`, 'stderr');
            }
        }
    }

    saveSessionState() {
        const state = {
            activePath: this.activePath,
            tabs: Array.from(this.openTabs.values()).map(tab => ({
                path: tab.path,
                name: tab.name
            }))
        };
        localStorage.setItem('prig_ide_session', JSON.stringify(state));
    }

    async restoreSessionState() {
        try {
            const savedStr = localStorage.getItem('prig_ide_session');
            if (!savedStr) return;
            const state = JSON.parse(savedStr);
            if (!state || !state.tabs) return;
            this._restaurando = true;

            for (const tab of state.tabs) {
                try {
                    const res = await fetch(`/api/file?path=${encodeURIComponent(tab.path)}`);
                    const data = await res.json();
                    if (data.content !== undefined) {
                        this.openFile(tab.path, tab.name, data.content, data.notebook_data);
                    }
                } catch (e) {
                    console.error('Error al restaurar tab:', tab.path, e);
                }
            }
            if (state.activePath && this.openTabs.has(state.activePath)) {
                this.setActiveTab(state.activePath);
            }
        } catch(e) {
            console.error('Error leyendo estado de sesion:', e);
        } finally {
            this._restaurando = false;
        }
    }
}

window.editorMgr = new EditorManager();

// Última red de seguridad: cerrar la ventana de Prig con trabajo sin guardar
// pedirá confirmación al navegador o al contenedor nativo.
window.addEventListener('beforeunload', (e) => {
    if (window.__prigSinAvisoAlSalir) return;
    if (window.editorMgr && window.editorMgr.hasUnsavedChanges()) {
        e.preventDefault();
        e.returnValue = '';
        return '';
    }
});
