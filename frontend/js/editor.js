class EditorManager {
    constructor() {
        this.numColumns = 1; // 1, 2 o 3 columnas
        this.activeCol = 0;  // 0, 1 o 2 (columna activa con foco)
        this.colWidths = [100]; // Porcentajes de ancho
        this.openTabs = new Map(); // path -> { name, path, model, isNotebook, notebookData, savedContent }
        this.panes = [
            { id: 0, containerEl: null, tabsEl: null, editor: null, tabs: [], activePath: null },
            { id: 1, containerEl: null, tabsEl: null, editor: null, tabs: [], activePath: null },
            { id: 2, containerEl: null, tabsEl: null, editor: null, tabs: [], activePath: null }
        ];
        this._isAutoCommenting = false;
        this._restaurando = false;
        this.nivelTransparencia = this.obtenerNivelTransparencia();
        this.fondoTransparente = this.nivelTransparencia > 0;
        this.initMonaco();
    }

    // Compatibilidad retroactiva: editor y activePath apuntan al panel activo
    get editor() {
        return this.panes[this.activeCol]?.editor || this.panes[0]?.editor || null;
    }

    set editor(val) {
        if (this.panes[this.activeCol]) this.panes[this.activeCol].editor = val;
        else if (this.panes[0]) this.panes[0].editor = val;
    }

    get activePath() {
        return this.panes[this.activeCol]?.activePath || this.panes[0]?.activePath || null;
    }

    set activePath(val) {
        if (this.panes[this.activeCol]) this.panes[this.activeCol].activePath = val;
        else if (this.panes[0]) this.panes[0].activePath = val;
    }

    hasEditor(ed) {
        return this.panes.some(p => p.editor === ed);
    }

    initMonaco() {
        // Enlazar contenedores DOM de cada panel inmediatamente
        this.panes[0].containerEl = document.getElementById('monaco-editor-container');
        this.panes[0].tabsEl = document.getElementById('editor-tabs');

        this.panes[1].containerEl = document.getElementById('monaco-editor-container-1');
        this.panes[1].tabsEl = document.getElementById('editor-tabs-1');

        this.panes[2].containerEl = document.getElementById('monaco-editor-container-2');
        this.panes[2].tabsEl = document.getElementById('editor-tabs-2');

        // Instancia inmediata para Col 0: si Monaco está disponible se usa, si no, fallback nativo
        this.panes[0].editor = this.createMonacoInstance(this.panes[0].containerEl, 0)
            || this.createFallbackEditorInstance(this.panes[0].containerEl, 0);

        // Iniciar cuaderno Jupyter
        if (window.notebookMgr) {
            window.notebookMgr.init(document.getElementById('notebook-view-container'));
        }

        // Iniciar controles de disposición y divisores redimensionables
        this.initLayoutControls();
        this.setupResizers();
        this.setupTabDragAndDrop();
        this.pintarVacio();

        // Aplicar transparencia inicial guardada
        this.aplicarFondoTransparente(this.fondoTransparente);

        // Restaurar disposición y sesión de inmediato
        this.restoreLayoutState();
        this.restoreSessionState();

        // Atajo global Alt+T para alternar fondo de código transparente
        window.addEventListener('keydown', (e) => {
            if (e.altKey && (e.key === 't' || e.key === 'T') && !e.ctrlKey && !e.metaKey) {
                e.preventDefault();
                this.alternarFondoTransparente();
            }
        });

        // Carga diferida o actualización con Monaco si require está presente
        if (typeof require !== 'undefined' && typeof require.config === 'function') {
            try {
                require.config({ paths: { 'vs': 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs' } });
                require(['vs/editor/editor.main'], () => {
                    this._onMonacoAvailable();
                });
            } catch (e) {
                console.warn('Monaco offline fallback activo:', e);
            }
        }
    }

    _onMonacoAvailable() {
        if (typeof monaco === 'undefined' || !monaco.editor) return;

        // Registrar tema transparente nativo para Monaco
        monaco.editor.defineTheme('prig-transparent', {
            base: 'vs-dark',
            inherit: true,
            rules: [],
            colors: {
                'editor.background': '#00000000',
                'editorGutter.background': '#00000000',
                'editor.lineHighlightBackground': 'rgba(255,255,255,0.04)',
                'editorLineNumber.foreground': '#7f849c',
                'editorLineNumber.activeForeground': '#00f0ff',
                'editorIndentGuide.background': 'rgba(255,255,255,0.06)'
            }
        });

        if (window.sintaxisMgr) {
            window.sintaxisMgr.aplicar();
        } else {
            monaco.editor.defineTheme('prig-dark', {
                base: 'vs-dark',
                inherit: true,
                rules: [],
                colors: {
                    'editor.background': this.fondoTransparente ? '#00000000' : '#1e1e1e',
                    'editorGutter.background': this.fondoTransparente ? '#00000000' : '#1e1e1e',
                    'editor.lineHighlightBackground': '#2a2d2e',
                    'editorLineNumber.foreground': '#858585',
                    'editorLineNumber.activeForeground': '#cccccc',
                    'editorIndentGuide.background': '#333333'
                }
            });
        }

        if (this.fondoTransparente) {
            this.aplicarFondoTransparente(true);
        }

        // Si alguna columna usaba el editor fallback, reemplazarla por Monaco conservando contenido
        for (let i = 0; i < this.numColumns; i++) {
            const pane = this.panes[i];
            if (pane.editor && pane.editor.isFallback) {
                const currentVal = pane.editor.getValue();
                pane.containerEl.innerHTML = '';
                pane.editor = this.createMonacoInstance(pane.containerEl, i);
                if (pane.activePath && this.openTabs.has(pane.activePath)) {
                    const tab = this.openTabs.get(pane.activePath);
                    const ext = (tab.name || '').split('.').pop().toLowerCase();
                    const lang = this.getLanguageForExt(ext);
                    tab.model = monaco.editor.createModel(currentVal || tab.savedContent || '', lang);
                    pane.editor.setModel(tab.model);
                }
            }
        }

        // Actualizar modelos que se hayan creado como fallback
        for (const [p, tab] of this.openTabs.entries()) {
            if (tab.model && tab.model.isFallback && !tab.isImage) {
                const ext = (tab.name || '').split('.').pop().toLowerCase();
                const lang = this.getLanguageForExt(ext);
                const currentContent = typeof tab.model.getValue === 'function' ? tab.model.getValue() : (tab.savedContent || '');
                tab.model = monaco.editor.createModel(currentContent, lang);
                tab.model.onDidChangeContent(() => {
                    this.checkAutoComment(tab.path);
                    this.onContentChanged(tab.path);
                });
            }
        }

        // Registrar CodeLens interactivo para prompts en línea "Prig//: " (global a Monaco)
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
    }

    getLanguageForExt(ext) {
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
        return (ext && langMap[ext.toLowerCase()]) || 'plaintext';
    }

    createFallbackModel(content, lang = 'plaintext') {
        let val = String(content || '');
        const listeners = [];
        return {
            isFallback: true,
            language: lang,
            getValue: () => val,
            setValue: (newVal) => {
                val = String(newVal || '');
                listeners.forEach(cb => { try { cb(); } catch (e) {} });
            },
            onDidChangeContent: (cb) => {
                listeners.push(cb);
                return { dispose: () => { const idx = listeners.indexOf(cb); if (idx >= 0) listeners.splice(idx, 1); } };
            },
            getLineCount: () => val.split('\n').length,
            getLinesContent: () => val.split('\n'),
            getLineContent: (ln) => val.split('\n')[ln - 1] || '',
            getLineMaxColumn: (ln) => (val.split('\n')[ln - 1] || '').length + 1,
            getValueInRange: (range) => {
                const lines = val.split('\n');
                if (!range) return val;
                const sl = Math.max(1, range.startLineNumber || 1) - 1;
                const el = Math.min(lines.length, range.endLineNumber || lines.length) - 1;
                if (sl === el) {
                    return (lines[sl] || '').substring((range.startColumn || 1) - 1, (range.endColumn || 1) - 1);
                }
                return lines.slice(sl, el + 1).join('\n');
            },
            dispose: () => { listeners.length = 0; }
        };
    }

    createFallbackEditorInstance(containerEl, colIndex) {
        if (!containerEl) return null;
        containerEl.innerHTML = '';

        const wrapper = document.createElement('div');
        wrapper.className = 'prig-fallback-editor';
        wrapper.style.display = 'flex';
        wrapper.style.width = '100%';
        wrapper.style.height = '100%';
        wrapper.style.background = '#181825';
        wrapper.style.color = '#cdd6f4';
        wrapper.style.fontFamily = "'Fira Code', 'Cascadia Code', Consolas, monospace";
        wrapper.style.fontSize = '13.5px';
        wrapper.style.position = 'relative';
        wrapper.style.overflow = 'hidden';

        // Gutter de números de línea
        const gutter = document.createElement('div');
        gutter.className = 'prig-fallback-gutter';
        gutter.style.width = '48px';
        gutter.style.padding = '8px 6px 8px 0';
        gutter.style.textAlign = 'right';
        gutter.style.background = '#11111b';
        gutter.style.color = '#585b70';
        gutter.style.borderRight = '1px solid #313244';
        gutter.style.userSelect = 'none';
        gutter.style.lineHeight = '1.5';
        gutter.style.overflow = 'hidden';
        gutter.style.flexShrink = '0';
        gutter.textContent = '1';

        // Textarea nativa de alto rendimiento
        const textarea = document.createElement('textarea');
        textarea.className = 'prig-fallback-textarea';
        textarea.style.flex = '1';
        textarea.style.height = '100%';
        textarea.style.padding = '8px 12px';
        textarea.style.background = 'transparent';
        textarea.style.color = '#cdd6f4';
        textarea.style.border = 'none';
        textarea.style.outline = 'none';
        textarea.style.resize = 'none';
        textarea.style.fontFamily = 'inherit';
        textarea.style.fontSize = 'inherit';
        textarea.style.lineHeight = '1.5';
        textarea.style.whiteSpace = 'pre';
        textarea.style.overflow = 'auto';
        textarea.style.tabSize = '4';
        textarea.spellcheck = false;
        textarea.setAttribute('autocomplete', 'off');
        textarea.setAttribute('autocorrect', 'off');
        textarea.setAttribute('autocapitalize', 'off');

        wrapper.appendChild(gutter);
        wrapper.appendChild(textarea);
        containerEl.appendChild(wrapper);

        const updateGutter = () => {
            const lines = (textarea.value || '').split('\n').length;
            let gText = '';
            for (let i = 1; i <= lines; i++) {
                gText += i + '\n';
            }
            gutter.textContent = gText;
        };

        textarea.addEventListener('scroll', () => {
            gutter.scrollTop = textarea.scrollTop;
        });

        const commands = new Map();

        const instance = {
            isFallback: true,
            colIndex,
            containerEl,
            wrapper,
            gutter,
            textarea,
            currentModel: null,
            focus: () => textarea.focus(),
            layout: () => updateGutter(),
            // Lo que se aplica antes de que cargue Monaco (preferencias de apariencia y vista): el resto de opciones
            // no tiene equivalente en una textarea y se ignora
            updateOptions: (o) => {
                if (!o) return;
                if (o.fontSize) wrapper.style.fontSize = `${o.fontSize}px`;
                if (o.fontFamily) wrapper.style.fontFamily = o.fontFamily;
                if (o.tabSize) textarea.style.tabSize = String(o.tabSize);
                if (o.wordWrap) textarea.style.whiteSpace = o.wordWrap === 'on' ? 'pre-wrap' : 'pre';
                if (o.lineNumbers) gutter.style.display = o.lineNumbers === 'off' ? 'none' : '';
            },
            getAction: () => null,
            getValue: () => textarea.value,
            setValue: (val) => {
                textarea.value = val || '';
                updateGutter();
                if (instance.currentModel && typeof instance.currentModel.setValue === 'function') {
                    if (instance.currentModel.getValue() !== textarea.value) {
                        instance.currentModel.setValue(textarea.value);
                    }
                }
            },
            setModel: (model) => {
                instance.currentModel = model;
                const content = model ? (typeof model.getValue === 'function' ? model.getValue() : '') : '';
                textarea.value = content;
                updateGutter();
            },
            getModel: () => instance.currentModel,
            getPosition: () => {
                const pos = textarea.selectionStart || 0;
                const lines = textarea.value.substring(0, pos).split('\n');
                const line = lines.length;
                const col = lines[lines.length - 1].length + 1;
                return { lineNumber: line, column: col };
            },
            setPosition: (pos) => {
                if (!pos) return;
                const lines = textarea.value.split('\n');
                let offset = 0;
                const targetLine = Math.min(lines.length, Math.max(1, pos.lineNumber || 1));
                for (let i = 0; i < targetLine - 1; i++) {
                    offset += lines[i].length + 1;
                }
                offset += Math.max(0, (pos.column || 1) - 1);
                textarea.selectionStart = textarea.selectionEnd = offset;
            },
            getSelection: () => {
                const start = textarea.selectionStart || 0;
                const end = textarea.selectionEnd || 0;
                return {
                    isEmpty: () => start === end,
                    startOffset: start,
                    endOffset: end
                };
            },
            executeEdits: (source, edits) => {
                if (!edits || edits.length === 0) return;
                edits.forEach(e => {
                    if (e.text !== undefined) {
                        const start = textarea.selectionStart;
                        const end = textarea.selectionEnd;
                        textarea.setRangeText(e.text, start, end, 'end');
                    }
                });
                updateGutter();
                if (instance.currentModel && typeof instance.currentModel.setValue === 'function') {
                    instance.currentModel.setValue(textarea.value);
                }
            },
            addCommand: (keybinding, handler) => {
                commands.set(keybinding, handler);
            },
            onDidFocusEditorWidget: (cb) => {
                textarea.addEventListener('focus', cb);
            },
            onDidChangeCursorPosition: (cb) => {
                textarea.addEventListener('keyup', cb);
                textarea.addEventListener('click', cb);
            }
        };

        textarea.addEventListener('input', () => {
            updateGutter();
            if (instance.currentModel && typeof instance.currentModel.setValue === 'function') {
                instance.currentModel.setValue(textarea.value);
            }
        });

        textarea.addEventListener('keydown', (e) => {
            if (e.key === 'Tab') {
                e.preventDefault();
                const start = textarea.selectionStart;
                const end = textarea.selectionEnd;
                textarea.setRangeText('    ', start, end, 'end');
                updateGutter();
                if (instance.currentModel && typeof instance.currentModel.setValue === 'function') {
                    instance.currentModel.setValue(textarea.value);
                }
                return;
            }
            if ((e.ctrlKey || e.metaKey) && (e.key === 's' || e.key === 'S')) {
                e.preventDefault();
                if (window.editorMgr && typeof window.editorMgr.saveActiveFile === 'function') {
                    window.editorMgr.saveActiveFile();
                }
                return;
            }
        });

        textarea.addEventListener('focus', () => {
            this.setActivePane(colIndex);
        });

        // Mientras carga Monaco, el resto del IDE llama a métodos de Monaco que una textarea no tiene: los eventos
        // (on…) devuelven algo que se puede soltar, las consultas (get…) nada, y lo demás no hace nada. Sin esto,
        // la primera llamada que faltaba cortaba el arranque de su módulo (pasaba en WebKitGTK, que carga Monaco
        // más tarde).
        return new Proxy(instance, {
            get(objetivo, nombre) {
                if (nombre in objetivo || typeof nombre !== 'string') return objetivo[nombre];
                if (/^on[A-Z]/.test(nombre)) return () => ({ dispose() {} });
                if (/^get[A-Z]/.test(nombre)) return () => null;
                return () => undefined;
            },
        });
    }

    /** Crea una instancia de Monaco Editor para una columna dada */
    createMonacoInstance(containerEl, colIndex) {
        if (!containerEl || typeof monaco === 'undefined') return null;

        const ed = monaco.editor.create(containerEl, {
            value: '',
            language: 'python',
            theme: this.fondoTransparente
                ? 'prig-transparent'
                : (window.sintaxisMgr ? 'prig-custom-syntax' : (localStorage.getItem('prig_editor_theme') || 'vs-dark')),
            automaticLayout: true,
            fontSize: parseInt(localStorage.getItem('prig_editor_font_size') || '14', 10),
            fontFamily: "'Fira Code', monospace",
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            smoothScrolling: true
        });

        // Evento de foco: actualizar la columna activa
        ed.onDidFocusEditorWidget(() => {
            this.setActivePane(colIndex);
        });

        // Sincronización del cursor y mecanografía con el motor de efectos de fondo (Robot Matrix Artillero)
        let _ultimoDisparoTiempo = 0;
        const obtenerCoordsCursor = () => {
            const pos = ed.getPosition();
            if (!pos) return null;
            const coords = ed.getScrolledVisiblePosition(pos);
            const domNode = ed.getDomNode();
            if (!coords || !domNode) return null;
            const rect = domNode.getBoundingClientRect();
            return {
                x: rect.left + coords.left,
                y: rect.top + coords.top + (coords.height ? coords.height / 2 : 10)
            };
        };

        ed.onDidChangeCursorPosition((e) => {
            if (window.motorMovimiento) {
                const pt = obtenerCoordsCursor();
                if (pt) window.motorMovimiento.notificarPosicionCursor(pt.x, pt.y);
            }
            if (window.DIRECTOR_ASCII && window.DIRECTOR_ASCII.evaluador && typeof window.DIRECTOR_ASCII.evaluador.notificarCursor === 'function') {
                const pos = ed.getPosition();
                if (pos) {
                    window.DIRECTOR_ASCII.evaluador.notificarCursor(pos.lineNumber, pos.column);
                }
            }
            if (window.EditorRazonamiento) {
                window.EditorRazonamiento.notificarCursor(ed);
            }
        });

        // Sincronización continua de corchetes y flechas con el scroll de Monaco
        ed.onDidScrollChange(() => {
            if (window.EditorRazonamiento) {
                window.EditorRazonamiento.actualizarOverlay();
            }
        });

        ed.onKeyDown((e) => {
            if (!window.motorMovimiento) return;
            const ahora = performance.now();
            if (ahora - _ultimoDisparoTiempo < 35) return; // Throttling 35ms para evitar saturación
            _ultimoDisparoTiempo = ahora;

            const key = (e.browserEvent && e.browserEvent.key && e.browserEvent.key.length === 1) ? e.browserEvent.key : '1';
            const pt = obtenerCoordsCursor();
            if (pt) {
                window.motorMovimiento.dispararHaciaCursor(pt.x, pt.y, key);
            }
        });

        // Disparo de evaluación de código por el Evaluador ASCII e impulso físico de resortes
        let _timerEvaluacionCodigo = null;
        ed.onDidChangeModelContent(() => {
            if (window.DIRECTOR_ASCII && window.DIRECTOR_ASCII.evaluador && typeof window.DIRECTOR_ASCII.evaluador.aplicarImpulso === 'function') {
                window.DIRECTOR_ASCII.evaluador.aplicarImpulso((Math.random() - 0.5) * 1.2, (Math.random() - 0.5) * 0.8);
            }
            if (window.EditorRazonamiento) {
                window.EditorRazonamiento.alCambiarCodigo(ed);
            }
            if (_timerEvaluacionCodigo) clearTimeout(_timerEvaluacionCodigo);
            _timerEvaluacionCodigo = setTimeout(() => {
                if (window.DIRECTOR_ASCII) {
                    window.DIRECTOR_ASCII.dispararDecisionDirector('pausa_escritura');
                }
            }, 6000);
        });

        // --- Atajos Nativos VS Code Registrados Directamente en Monaco ---
        // Atajo Ctrl+S: Guardar archivo
        ed.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
            if (window.app) window.app.saveCurrentFile();
        });

        // Atajo Ctrl+\: Dividir editor al lado (panel derecho)
        ed.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Backslash, () => {
            this.splitRight();
        });

        // Atajo F5 y Ctrl+F5: Ejecutar archivo/código
        ed.addCommand(monaco.KeyCode.F5, () => {
            if (window.app) window.app.runCode();
        });
        ed.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.F5, () => {
            if (window.app) window.app.runCode();
        });

        // Atajo Shift+Enter: Ejecutar selección o celda de cuaderno
        ed.addCommand(monaco.KeyMod.Shift | monaco.KeyCode.Enter, () => {
            if (window.notebookMgr && window.notebookMgr.activo) {
                window.notebookMgr.runSingleCell(window.notebookMgr.celdaActiva || 0);
            } else if (window.IDE && typeof window.IDE.ejecutarSeleccion === 'function') {
                window.IDE.ejecutarSeleccion();
            } else if (window.app) {
                window.app.runCode();
            }
        });

        // Atajo Ctrl+Enter: Prompt en línea si existe Prig//:, celda en cuaderno, o insertar línea debajo (VS Code estándar)
        ed.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => {
            const position = ed.getPosition();
            if (position) {
                let targetLine = position.lineNumber;
                let lineContent = ed.getModel()?.getLineContent(targetLine) || '';
                let match = lineContent.match(/Prig\/\/:\s*(.*)$/i);

                if (!match && targetLine > 1) {
                    const prevContent = ed.getModel()?.getLineContent(targetLine - 1) || '';
                    const prevMatch = prevContent.match(/Prig\/\/:\s*(.*)$/i);
                    if (prevMatch) {
                        targetLine = targetLine - 1;
                        lineContent = prevContent;
                        match = prevMatch;
                    }
                }

                if (match) {
                    const promptText = match[1].replace(/(-->|\*\/)\s*$/, '').trim();
                    this.executeInlinePrompt(targetLine, promptText, ed);
                    return;
                }
            }

            if (window.notebookMgr && window.notebookMgr.activo) {
                window.notebookMgr.runSingleCell(window.notebookMgr.celdaActiva || 0);
                return;
            }

            const accion = ed.getAction('editor.action.insertLineAfter');
            if (accion) accion.run();
        });

        // Atajo Ctrl+Shift+Enter: Insertar línea encima
        ed.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyMod.Shift | monaco.KeyCode.Enter, () => {
            const accion = ed.getAction('editor.action.insertLineBefore');
            if (accion) accion.run();
        });

        // Atajo Shift+Alt+Down: Duplicar línea abajo (VS Code estándar)
        ed.addCommand(monaco.KeyMod.Shift | monaco.KeyMod.Alt | monaco.KeyCode.DownArrow, () => {
            const accion = ed.getAction('editor.action.copyLinesDownAction');
            if (accion) accion.run();
        });

        // Atajo Shift+Alt+Up: Duplicar línea arriba (VS Code estándar)
        ed.addCommand(monaco.KeyMod.Shift | monaco.KeyMod.Alt | monaco.KeyCode.UpArrow, () => {
            const accion = ed.getAction('editor.action.copyLinesUpAction');
            if (accion) accion.run();
        });

        // Atajo Alt+Down: Mover línea abajo
        ed.addCommand(monaco.KeyMod.Alt | monaco.KeyCode.DownArrow, () => {
            const accion = ed.getAction('editor.action.moveLinesDownAction');
            if (accion) accion.run();
        });

        // Atajo Alt+Up: Mover línea arriba
        ed.addCommand(monaco.KeyMod.Alt | monaco.KeyCode.UpArrow, () => {
            const accion = ed.getAction('editor.action.moveLinesUpAction');
            if (accion) accion.run();
        });

        // Atajo Ctrl+Alt+Down: Añadir cursor abajo
        ed.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyMod.Alt | monaco.KeyCode.DownArrow, () => {
            const accion = ed.getAction('editor.action.insertCursorBelow');
            if (accion) accion.run();
        });

        // Atajo Ctrl+Alt+Up: Añadir cursor arriba
        ed.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyMod.Alt | monaco.KeyCode.UpArrow, () => {
            const accion = ed.getAction('editor.action.insertCursorAbove');
            if (accion) accion.run();
        });

        // Atajo Ctrl+Shift+K: Eliminar línea
        ed.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyMod.Shift | monaco.KeyCode.KeyK, () => {
            const accion = ed.getAction('editor.action.deleteLines');
            if (accion) accion.run();
        });

        // Atajo Shift+Alt+F: Formatear documento
        ed.addCommand(monaco.KeyMod.Shift | monaco.KeyMod.Alt | monaco.KeyCode.KeyF, () => {
            const accion = ed.getAction('editor.action.formatDocument');
            if (accion) accion.run();
        });

        // Atajo Ctrl+D: Añadir siguiente coincidencia a la selección
        ed.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyD, () => {
            const accion = ed.getAction('editor.action.addSelectionToNextFindMatch');
            if (accion) accion.run();
        });

        // Atajo Ctrl+U: Deshacer última selección o cursor
        ed.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyU, () => {
            ed.trigger('prig', 'cursorUndo', null);
        });

        // Atajo Ctrl+Shift+L: Seleccionar todas las coincidencias
        ed.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyMod.Shift | monaco.KeyCode.KeyL, () => {
            const accion = ed.getAction('editor.action.selectHighlights');
            if (accion) accion.run();
        });

        // Atajo F2: Renombrar símbolo
        ed.addCommand(monaco.KeyCode.F2, () => {
            const accion = ed.getAction('editor.action.rename');
            if (accion) accion.run();
        });

        // Atajo F12: Ir a definición
        ed.addCommand(monaco.KeyCode.F12, () => {
            const accion = ed.getAction('editor.action.revealDefinition');
            if (accion) accion.run();
        });

        // Atajo Alt+F12: Vista previa de definición
        ed.addCommand(monaco.KeyMod.Alt | monaco.KeyCode.F12, () => {
            const accion = ed.getAction('editor.action.peekDefinition');
            if (accion) accion.run();
        });

        // Atajo Ctrl+F12: Ir a implementación
        ed.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.F12, () => {
            const accion = ed.getAction('editor.action.goToImplementation');
            if (accion) accion.run();
        });

        // Atajo Shift+F12: Ver referencias
        ed.addCommand(monaco.KeyMod.Shift | monaco.KeyCode.F12, () => {
            const accion = ed.getAction('editor.action.goToReferences');
            if (accion) accion.run();
        });

        // Atajos Ctrl+1, Ctrl+2, Ctrl+3: Enfocar columna 1, 2, 3
        ed.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Digit1, () => {
            this.setActivePane(0);
            if (this.panes[0]?.editor) this.panes[0].editor.focus();
        });
        ed.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Digit2, () => {
            this.setActivePane(1);
            if (this.panes[1]?.editor) this.panes[1].editor.focus();
        });
        ed.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Digit3, () => {
            this.setActivePane(2);
            if (this.panes[2]?.editor) this.panes[2].editor.focus();
        });

        // Atajo Ctrl+W: Cerrar pestaña en el panel activo
        ed.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyW, () => {
            if (this.activePath) this.closeTabInPane(this.activeCol, this.activePath);
        });

        // Atajos Ctrl+PageDown / Ctrl+PageUp: Siguiente / anterior pestaña
        ed.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.PageDown, () => {
            if (window.IDE && typeof window.IDE.cambiarPestana === 'function') window.IDE.cambiarPestana(+1);
        });
        ed.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.PageUp, () => {
            if (window.IDE && typeof window.IDE.cambiarPestana === 'function') window.IDE.cambiarPestana(-1);
        });

        window.dispatchEvent(new CustomEvent('prig:editor-creado', { detail: { editor: ed, principal: (colIndex === 0) } }));
        return ed;
    }

    /** Obtiene o inicializa de forma perezosa el editor de una columna secundaria */
    getOrCreatePaneEditor(colIndex) {
        if (colIndex < 0 || colIndex >= 3) return null;
        if (!this.panes[colIndex].editor) {
            this.panes[colIndex].editor = this.createMonacoInstance(this.panes[colIndex].containerEl, colIndex)
                || this.createFallbackEditorInstance(this.panes[colIndex].containerEl, colIndex);
        }
        return this.panes[colIndex].editor;
    }

    /** Inicializa los botones de la barra de disposición y acciones por columna */
    initLayoutControls() {
        const btnCol1 = document.getElementById('btn-editor-cols-1');
        const btnCol2 = document.getElementById('btn-editor-cols-2');
        const btnCol3 = document.getElementById('btn-editor-cols-3');
        const btnSplit = document.getElementById('btn-editor-split-side');

        if (btnCol1) btnCol1.onclick = () => this.setColumnLayout(1);
        if (btnCol2) btnCol2.onclick = () => this.setColumnLayout(2);
        if (btnCol3) btnCol3.onclick = () => this.setColumnLayout(3);
        if (btnSplit) btnSplit.onclick = () => this.splitRight();

        // Botones de división inline en cada columna [data-split-col]
        document.querySelectorAll('[data-split-col]').forEach(btn => {
            btn.onclick = (e) => {
                e.stopPropagation();
                const col = parseInt(btn.dataset.splitCol, 10);
                const activePath = this.panes[col]?.activePath || this.activePath;
                this.splitRight(activePath);
            };
        });

        // Botones de cierre y movimiento en cabeceras de columnas
        document.querySelectorAll('[data-cerrar-col]').forEach(btn => {
            btn.onclick = (e) => {
                e.stopPropagation();
                const col = parseInt(btn.dataset.cerrarCol, 10);
                this.closeColumn(col);
            };
        });

        document.querySelectorAll('[data-mover-izq]').forEach(btn => {
            btn.onclick = (e) => {
                e.stopPropagation();
                const col = parseInt(btn.dataset.moverIzq, 10);
                const activePath = this.panes[col].activePath;
                if (activePath && col > 0) {
                    this.moveTabToPane(activePath, col, col - 1);
                }
            };
        });

        document.querySelectorAll('[data-mover-der]').forEach(btn => {
            btn.onclick = (e) => {
                e.stopPropagation();
                const col = parseInt(btn.dataset.moverDer, 10);
                const activePath = this.panes[col].activePath;
                if (activePath) {
                    const destCol = Math.min(2, col + 1);
                    this.moveTabToPane(activePath, col, destCol);
                }
            };
        });

        // Clic en la columna para enfocarla
        [0, 1, 2].forEach(colIndex => {
            const colEl = document.getElementById(`editor-col-${colIndex}`);
            if (colEl) {
                colEl.addEventListener('click', (e) => {
                    if (this.activeCol !== colIndex) {
                        this.setActivePane(colIndex);
                    }
                });
            }
        });
    }

    /** Cambia la disposición a 1, 2 o 3 columnas */
    setColumnLayout(cols, save = true) {
        cols = Math.max(1, Math.min(3, parseInt(cols, 10) || 1));
        this.numColumns = cols;

        // Actualizar botones de disposición
        document.querySelectorAll('.editor-layout-btn[data-cols]').forEach(btn => {
            btn.classList.toggle('active', parseInt(btn.dataset.cols, 10) === cols);
        });

        const infoCols = document.getElementById('editor-layout-info-cols');
        if (infoCols) {
            infoCols.textContent = `(${cols} Columna${cols > 1 ? 's' : ''})`;
        }

        const col0 = document.getElementById('editor-col-0');
        const resizer0 = document.getElementById('editor-resizer-0');
        const col1 = document.getElementById('editor-col-1');
        const resizer1 = document.getElementById('editor-resizer-1');
        const col2 = document.getElementById('editor-col-2');
        const actions0 = document.getElementById('editor-col-actions-0');

        if (cols === 1) {
            if (resizer0) resizer0.style.display = 'none';
            if (col1) col1.style.display = 'none';
            if (resizer1) resizer1.style.display = 'none';
            if (col2) col2.style.display = 'none';
            if (actions0) actions0.style.display = 'none';

            if (col0) {
                col0.style.flex = '1 1 100%';
                col0.style.width = '100%';
            }

            // Mover pestañas huérfanas de Col 1 y Col 2 a Col 0 para no perder trabajo
            [1, 2].forEach(ci => {
                const p = this.panes[ci];
                if (p.tabs && p.tabs.length) {
                    p.tabs.forEach(t => {
                        if (!this.panes[0].tabs.includes(t)) this.panes[0].tabs.push(t);
                    });
                    p.tabs = [];
                    p.activePath = null;
                }
            });

            this.setActivePane(0);
        } else if (cols === 2) {
            if (col1) col1.style.display = 'flex';
            if (resizer0) resizer0.style.display = 'block';
            if (resizer1) resizer1.style.display = 'none';
            if (col2) col2.style.display = 'none';
            if (actions0) actions0.style.display = 'flex';

            // Mover pestañas de Col 2 a Col 1
            const p2 = this.panes[2];
            if (p2.tabs && p2.tabs.length) {
                p2.tabs.forEach(t => {
                    if (!this.panes[1].tabs.includes(t)) this.panes[1].tabs.push(t);
                });
                p2.tabs = [];
                p2.activePath = null;
            }

            this.getOrCreatePaneEditor(1);

            // Ajustar anchos (50% / 50% por defecto o restaurados)
            const w0 = (this.colWidths && this.colWidths.length >= 2 && this.colWidths[0] > 15 && this.colWidths[0] < 85) ? this.colWidths[0] : 50;
            if (col0) { col0.style.flex = 'none'; col0.style.width = `${w0}%`; }
            if (col1) { col1.style.flex = 'none'; col1.style.width = `${100 - w0}%`; }

            // Si Col 1 no tiene pestañas y Col 0 tiene varias, mover una o clonar la activa para ver 2 códigos
            // (no cuando se abre a propósito un archivo en esa columna: ese archivo la ocupa)
            if (this._abriendoEnColumna) {
                // nada
            } else if (this.panes[1].tabs.length === 0 && this.panes[0].tabs.length > 1) {
                const moverRuta = this.panes[0].tabs[1] || this.panes[0].tabs[this.panes[0].tabs.length - 1];
                this.moveTabToPane(moverRuta, 0, 1);
            } else if (this.panes[1].tabs.length === 0 && this.panes[0].activePath) {
                this.openFileInPane(1, this.panes[0].activePath);
            }
        } else if (cols === 3) {
            if (col1) col1.style.display = 'flex';
            if (resizer0) resizer0.style.display = 'block';
            if (col2) col2.style.display = 'flex';
            if (resizer1) resizer1.style.display = 'block';
            if (actions0) actions0.style.display = 'flex';

            this.getOrCreatePaneEditor(1);
            this.getOrCreatePaneEditor(2);

            // 33.33% cada columna
            if (col0) { col0.style.flex = 'none'; col0.style.width = '33.33%'; }
            if (col1) { col1.style.flex = 'none'; col1.style.width = '33.33%'; }
            if (col2) { col2.style.flex = 'none'; col2.style.width = '33.34%'; }

            // Distribuir pestañas abiertas entre las 3 columnas si están vacías
            if (this.panes[1].tabs.length === 0 && this.panes[0].tabs.length >= 2) {
                const mover1 = this.panes[0].tabs[1];
                this.moveTabToPane(mover1, 0, 1);
            }
            if (this.panes[2].tabs.length === 0 && this.panes[0].tabs.length >= 2) {
                const mover2 = this.panes[0].tabs[this.panes[0].tabs.length - 1];
                this.moveTabToPane(mover2, 0, 2);
            } else if (this.panes[2].tabs.length === 0 && this.panes[1].tabs.length >= 2) {
                const mover2 = this.panes[1].tabs[this.panes[1].tabs.length - 1];
                this.moveTabToPane(mover2, 1, 2);
            } else if (this.panes[2].tabs.length === 0 && this.panes[0].activePath) {
                this.openFileInPane(2, this.panes[0].activePath);
            }
        }

        this.renderTabs();
        this.refreshEditorLayouts();
        if (save) this.saveLayoutState();
    }

    /** Cierra una columna específica y fusiona sus archivos con la anterior */
    closeColumn(colIndex) {
        if (colIndex <= 0 || colIndex >= 3) return;
        const targetCol = colIndex - 1;
        const p = this.panes[colIndex];
        if (p.tabs && p.tabs.length) {
            p.tabs.forEach(t => {
                if (!this.panes[targetCol].tabs.includes(t)) {
                    this.panes[targetCol].tabs.push(t);
                }
            });
            p.tabs = [];
            p.activePath = null;
        }

        const newCols = Math.max(1, this.numColumns - 1);
        this.setColumnLayout(newCols);
        this.setActivePane(targetCol);
    }

    /** Cambia el panel activo */
    setActivePane(colIndex) {
        colIndex = Math.max(0, Math.min(this.numColumns - 1, colIndex));
        this.activeCol = colIndex;

        // Actualizar clases .activa
        [0, 1, 2].forEach(ci => {
            const el = document.getElementById(`editor-col-${ci}`);
            if (el) el.classList.toggle('activa', ci === colIndex);
        });

        // Actualizar pestañas activas
        this.renderTabs();

        const activeP = this.panes[colIndex];
        if (activeP && activeP.activePath) {
            window.dispatchEvent(new CustomEvent('prig:pestana-activa', { detail: { path: activeP.activePath } }));
        }

        if (window.IDE && typeof window.IDE.pintarEstado === 'function') {
            window.IDE.pintarEstado();
        }
    }

    /** Refresca el layout de todos los editores activos */
    refreshEditorLayouts() {
        setTimeout(() => {
            for (let i = 0; i < this.numColumns; i++) {
                if (this.panes[i].editor) {
                    this.panes[i].editor.layout();
                }
            }
        }, 50);
    }

    /** Configura los divisores arrastrables con el ratón */
    setupResizers() {
        const resizer0 = document.getElementById('editor-resizer-0');
        const resizer1 = document.getElementById('editor-resizer-1');
        const container = document.getElementById('editor-grid-container');

        const iniciarArrastre = (e, index) => {
            e.preventDefault();
            const resizer = index === 0 ? resizer0 : resizer1;
            resizer?.classList.add('arrastrando');
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';

            const rect = container.getBoundingClientRect();
            const totalWidth = rect.width;

            const onMouseMove = (moveEv) => {
                const offsetX = moveEv.clientX - rect.left;
                if (this.numColumns === 2) {
                    let pct0 = Math.max(15, Math.min(85, (offsetX / totalWidth) * 100));
                    let pct1 = 100 - pct0;
                    this.colWidths = [pct0, pct1];
                    const c0 = document.getElementById('editor-col-0');
                    const c1 = document.getElementById('editor-col-1');
                    if (c0) c0.style.width = `${pct0}%`;
                    if (c1) c1.style.width = `${pct1}%`;
                } else if (this.numColumns === 3) {
                    if (index === 0) {
                        let pct0 = Math.max(15, Math.min(60, (offsetX / totalWidth) * 100));
                        let resto = 100 - pct0;
                        let pct1 = resto / 2;
                        let pct2 = resto / 2;
                        this.colWidths = [pct0, pct1, pct2];
                        const c0 = document.getElementById('editor-col-0');
                        const c1 = document.getElementById('editor-col-1');
                        const c2 = document.getElementById('editor-col-2');
                        if (c0) c0.style.width = `${pct0}%`;
                        if (c1) c1.style.width = `${pct1}%`;
                        if (c2) c2.style.width = `${pct2}%`;
                    } else {
                        const c0 = document.getElementById('editor-col-0');
                        const w0 = c0 ? parseFloat(c0.style.width) || 33.33 : 33.33;
                        let pct01 = (offsetX / totalWidth) * 100;
                        let pct1 = Math.max(15, Math.min(70 - w0, pct01 - w0));
                        let pct2 = 100 - w0 - pct1;
                        this.colWidths = [w0, pct1, pct2];
                        const c1 = document.getElementById('editor-col-1');
                        const c2 = document.getElementById('editor-col-2');
                        if (c1) c1.style.width = `${pct1}%`;
                        if (c2) c2.style.width = `${pct2}%`;
                    }
                }
                this.refreshEditorLayouts();
            };

            const onMouseUp = () => {
                window.removeEventListener('mousemove', onMouseMove);
                window.removeEventListener('mouseup', onMouseUp);
                resizer?.classList.remove('arrastrando');
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
                this.refreshEditorLayouts();
                this.saveLayoutState();
            };

            window.addEventListener('mousemove', onMouseMove);
            window.addEventListener('mouseup', onMouseUp);
        };

        if (resizer0) {
            resizer0.addEventListener('mousedown', (e) => iniciarArrastre(e, 0));
            resizer0.addEventListener('dblclick', () => {
                if (this.numColumns === 2) {
                    this.colWidths = [50, 50];
                    const c0 = document.getElementById('editor-col-0');
                    const c1 = document.getElementById('editor-col-1');
                    if (c0) c0.style.width = '50%';
                    if (c1) c1.style.width = '50%';
                } else if (this.numColumns === 3) {
                    this.colWidths = [33.33, 33.33, 33.34];
                    const c0 = document.getElementById('editor-col-0');
                    const c1 = document.getElementById('editor-col-1');
                    const c2 = document.getElementById('editor-col-2');
                    if (c0) c0.style.width = '33.33%';
                    if (c1) c1.style.width = '33.33%';
                    if (c2) c2.style.width = '33.34%';
                }
                this.refreshEditorLayouts();
                this.saveLayoutState();
            });
        }

        if (resizer1) {
            resizer1.addEventListener('mousedown', (e) => iniciarArrastre(e, 1));
            resizer1.addEventListener('dblclick', () => {
                this.colWidths = [33.33, 33.33, 33.34];
                const c0 = document.getElementById('editor-col-0');
                const c1 = document.getElementById('editor-col-1');
                const c2 = document.getElementById('editor-col-2');
                if (c0) c0.style.width = '33.33%';
                if (c1) c1.style.width = '33.33%';
                if (c2) c2.style.width = '33.34%';
                this.refreshEditorLayouts();
                this.saveLayoutState();
            });
        }
    }

    /** Configura drag & drop para mover pestañas entre columnas del editor de código */
    setupTabDragAndDrop() {
        [0, 1, 2].forEach(colIndex => {
            const tabsEl = document.getElementById(colIndex === 0 ? 'editor-tabs' : `editor-tabs-${colIndex}`);
            const emptyEl = document.getElementById(`editor-col-empty-${colIndex}`);
            const colEl = document.getElementById(`editor-col-${colIndex}`);

            const zonas = [tabsEl, emptyEl, colEl].filter(Boolean);
            zonas.forEach(zona => {
                zona.addEventListener('dragover', (e) => {
                    if (!e.dataTransfer.types.includes('application/prig-code-tab')) return;
                    e.preventDefault();
                    e.dataTransfer.dropEffect = 'move';
                    if (colEl) colEl.classList.add('drag-over');
                    zona.classList.add('drag-over');
                });

                zona.addEventListener('dragleave', (e) => {
                    if (!e.relatedTarget || !zona.contains(e.relatedTarget)) {
                        zona.classList.remove('drag-over');
                        if (colEl && (!e.relatedTarget || !colEl.contains(e.relatedTarget))) {
                            colEl.classList.remove('drag-over');
                        }
                    }
                });

                zona.addEventListener('drop', (e) => {
                    if (!e.dataTransfer.types.includes('application/prig-code-tab')) return;
                    e.preventDefault();
                    zona.classList.remove('drag-over');
                    if (colEl) colEl.classList.remove('drag-over');
                    const rawData = e.dataTransfer.getData('application/prig-code-tab');
                    if (!rawData) return;
                    try {
                        const data = JSON.parse(rawData);
                        if (data && data.path) {
                            const fromCol = data.colIndex !== undefined ? data.colIndex : this.activeCol;
                            if (fromCol !== colIndex) {
                                this.moveTabToPane(data.path, fromCol, colIndex);
                            }
                        }
                    } catch (err) {
                        console.error('Error procesando drop de pestaña de código:', err);
                    }
                });
            });
        });
    }

    /** Abre un archivo pidiéndolo al backend */
    async openFileByPath(path, name = null, targetCol = null) {
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
            this.openFile(data.path || path, fileName, data.content, data.notebook_data, targetCol);
            return true;
        } catch (e) {
            console.error('Error abriendo archivo:', path, e);
            if (window.terminalMgr) {
                window.terminalMgr.appendLine(`[No se pudo abrir ${path}: ${e.message}]`, 'stderr');
            }
            return false;
        }
    }

    /** Abre un archivo en el editor, asegurando la existencia del modelo y agregándolo al panel correspondiente */
    openFile(path, name, content, notebookData = null, targetCol = null) {
        if (!this.panes[0].editor) {
            this.panes[0].editor = this.createMonacoInstance(this.panes[0].containerEl, 0)
                || this.createFallbackEditorInstance(this.panes[0].containerEl, 0);
        }
        if (!this.panes[0].editor) return;

        const isNotebook = name && name.endsWith('.ipynb');
        const ext = (name || '').split('.').pop().toLowerCase();
        const lang = this.getLanguageForExt(ext);
        const isImage = ['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'ico', 'bmp'].includes(ext);

        if (!this.openTabs.has(path)) {
            let model = null;
            if (isImage) {
                model = this.createFallbackModel(`[Imagen: ${name}]`, 'plaintext');
            } else if (typeof monaco !== 'undefined' && monaco.editor && monaco.editor.createModel) {
                model = monaco.editor.createModel(content || '', lang);
            } else {
                model = this.createFallbackModel(content || '', lang);
            }
            const tab = {
                name,
                path,
                model,
                isNotebook,
                notebookData,
                savedContent: content,
                isImage,
                imageUrl: `/api/file/raw?path=${encodeURIComponent(path)}`
            };
            this.openTabs.set(path, tab);

            if (model && typeof model.onDidChangeContent === 'function') {
                model.onDidChangeContent(() => {
                    this.checkAutoComment(tab.path);
                    this.onContentChanged(tab.path);
                });
            }
        } else {
            const tab = this.openTabs.get(path);
            if (tab.model && typeof tab.model.getValue === 'function' && tab.model.getValue() !== content) {
                tab.model.setValue(content || '');
            }
            tab.savedContent = content;
            tab.notebookData = notebookData;
        }

        const destCol = targetCol !== null ? targetCol : this.activeCol;
        if (destCol >= this.numColumns) {
            this._abriendoEnColumna = true;
            try {
                this.setColumnLayout(destCol + 1, false);
            } finally {
                this._abriendoEnColumna = false;
            }
        }

        const targetPane = this.panes[destCol];
        if (!targetPane.tabs.includes(path)) {
            targetPane.tabs.push(path);
        }

        this.setActiveTabInPane(destCol, path);
        const wrapper = document.getElementById('editor-area-wrapper');
        if (wrapper) wrapper.style.display = 'flex';
        const gridEl = document.getElementById('editor-grid-container');
        if (gridEl) gridEl.style.display = 'flex';
        const vacio = document.getElementById('editor-vacio');
        if (vacio) vacio.hidden = true;

        this.saveLayoutState();
        this.saveSessionState();

        if (!this._restaurando && window.workArea && window.workArea.activa !== 'editor') {
            window.workArea.activar('editor');
        }
        window.dispatchEvent(new CustomEvent('prig:archivo-abierto', { detail: { path } }));
    }

    /** Abre un archivo ya cargado en una columna específica */
    openFileInPane(colIndex, path) {
        if (!this.openTabs.has(path)) {
            this.openFileByPath(path, null, colIndex);
            return;
        }
        const targetPane = this.panes[colIndex];
        if (!targetPane.tabs.includes(path)) {
            targetPane.tabs.push(path);
        }
        this.setActiveTabInPane(colIndex, path);
    }

    /** Establece la pestaña activa en el panel actualmente enfocado (o el panel que contiene el archivo) */
    setActiveTab(path) {
        for (let i = 0; i < this.numColumns; i++) {
            if (this.panes[i].tabs && this.panes[i].tabs.includes(path)) {
                this.setActiveTabInPane(i, path);
                this.setActivePane(i);
                return;
            }
        }
        this.setActiveTabInPane(this.activeCol, path);
    }

    /** Establece la pestaña activa dentro de una columna dada */
    setActiveTabInPane(colIndex, path) {
        const tabData = this.openTabs.get(path);
        const pane = this.panes[colIndex];
        if (!pane || !tabData) return;

        pane.activePath = path;
        const ed = this.getOrCreatePaneEditor(colIndex);
        if (ed && tabData.model) {
            ed.setModel(tabData.model);
        }

        // Si la columna es 0 y es un cuaderno o imagen, manejar contenedores visuales
        if (colIndex === 0) {
            const monacoContainer = document.getElementById('monaco-editor-container');
            const notebookContainer = document.getElementById('notebook-view-container');
            const viewModeBar = document.getElementById('view-mode-bar');
            let imageContainer = document.getElementById('image-view-container');
            if (!imageContainer) {
                imageContainer = document.createElement('div');
                imageContainer.id = 'image-view-container';
                imageContainer.style.cssText = 'display:none; flex:1; align-items:center; justify-content:center; background:#11111b; overflow:auto; padding:20px;';
                if (monacoContainer && monacoContainer.parentElement) {
                    monacoContainer.parentElement.appendChild(imageContainer);
                }
            }

            if (tabData.isImage) {
                if (viewModeBar) viewModeBar.style.display = 'none';
                if (monacoContainer) monacoContainer.style.display = 'none';
                if (notebookContainer) notebookContainer.style.display = 'none';
                imageContainer.style.display = 'flex';
                imageContainer.innerHTML = `
                    <div style="text-align:center; max-width:90%; max-height:85%;">
                        <div style="margin-bottom:10px; color:var(--text-muted); font-size:12px; display:flex; align-items:center; justify-content:center; gap:8px;">
                            <i class="fa-solid fa-image" style="color:var(--accent-blue);"></i> <span>${this.escapeHtml ? this.escapeHtml(tabData.name) : tabData.name}</span>
                        </div>
                        <img src="${tabData.imageUrl}" alt="${this.escapeHtml ? this.escapeHtml(tabData.name) : tabData.name}" style="max-width:100%; max-height:70vh; object-fit:contain; border-radius:6px; box-shadow:0 8px 30px rgba(0,0,0,0.6); border:1px solid rgba(255,255,255,0.1);">
                    </div>
                `;
            } else if (tabData.isNotebook && tabData.notebookData) {
                if (imageContainer) imageContainer.style.display = 'none';
                if (viewModeBar) viewModeBar.style.display = 'flex';
                if (monacoContainer) monacoContainer.style.display = 'none';
                if (notebookContainer) {
                    notebookContainer.style.display = 'flex';
                    if (window.notebookMgr) window.notebookMgr.renderNotebook(tabData.notebookData);
                }
            } else {
                if (imageContainer) imageContainer.style.display = 'none';
                if (viewModeBar) viewModeBar.style.display = 'none';
                if (monacoContainer) monacoContainer.style.display = 'block';
                if (notebookContainer) notebookContainer.style.display = 'none';
            }
        }

        this.renderTabs();
        this.saveLayoutState();
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

    /** Cierra una pestaña en la columna activa (compatibilidad) */
    closeTab(path, event, forzar = false) {
        return this.closeTabInPane(this.activeCol, path, event, forzar);
    }

    /** Cierra una pestaña en una columna específica */
    closeTabInPane(colIndex, path, event = null, forzar = false) {
        if (event) event.stopPropagation();
        const tabData = this.openTabs.get(path);
        const pane = this.panes[colIndex];
        if (!pane) return false;

        // Si es el único panel donde está abierto el archivo y tiene cambios sin guardar
        const openInOtherPanes = this.panes.some((p, idx) => idx !== colIndex && p.tabs.includes(path));
        if (tabData && !openInOtherPanes && !forzar && this.isDirty(path)) {
            const nombre = tabData.name || path;
            if (!confirm(`"${nombre}" tiene cambios sin guardar.\n\n¿Cerrar de todos modos y perderlos?`)) {
                return false;
            }
        }

        // Remover de la columna
        pane.tabs = pane.tabs.filter(p => p !== path);

        // Si ya no está en ninguna columna, liberar modelo
        if (!openInOtherPanes && tabData) {
            if (tabData.model && typeof tabData.model.dispose === 'function') {
                tabData.model.dispose();
            }
            this.openTabs.delete(path);
            if (this._lastDirty) delete this._lastDirty[path];
            window.dispatchEvent(new CustomEvent('prig:pestana-cerrada', { detail: { path } }));
        }

        // Si se cerró la pestaña activa de esta columna, conmutar a la última o limpiar
        if (pane.activePath === path) {
            if (pane.tabs.length > 0) {
                this.setActiveTabInPane(colIndex, pane.tabs[pane.tabs.length - 1]);
            } else {
                pane.activePath = null;
                if (pane.editor) {
                    const emptyModel = (typeof monaco !== 'undefined' && monaco.editor)
                        ? monaco.editor.createModel('', 'plaintext')
                        : this.createFallbackModel('', 'plaintext');
                    pane.editor.setModel(emptyModel);
                }
                if (colIndex === 0) {
                    const viewModeBar = document.getElementById('view-mode-bar');
                    if (viewModeBar) viewModeBar.style.display = 'none';
                    const monacoContainer = document.getElementById('monaco-editor-container');
                    if (monacoContainer) monacoContainer.style.display = 'block';
                    const notebookContainer = document.getElementById('notebook-view-container');
                    if (notebookContainer) notebookContainer.style.display = 'none';
                }
            }
        }

        this.renderTabs();
        this.saveLayoutState();
        this.saveSessionState();
        return true;
    }

    /** Mueve una pestaña de una columna a otra */
    moveTabToPane(path, fromCol, toCol) {
        if (fromCol === toCol || !this.openTabs.has(path)) return;
        toCol = Math.max(0, Math.min(2, toCol));

        // Si la columna de destino no está visible, abrir la disposición adecuada
        if (toCol >= this.numColumns) {
            this.setColumnLayout(toCol + 1, false);
        }

        const sourcePane = this.panes[fromCol];
        const destPane = this.panes[toCol];

        // Remover de origen
        sourcePane.tabs = sourcePane.tabs.filter(p => p !== path);
        if (sourcePane.activePath === path) {
            sourcePane.activePath = sourcePane.tabs.length > 0 ? sourcePane.tabs[sourcePane.tabs.length - 1] : null;
            if (sourcePane.activePath) {
                this.setActiveTabInPane(fromCol, sourcePane.activePath);
            } else if (sourcePane.editor) {
                const emptyModel = (typeof monaco !== 'undefined' && monaco.editor)
                    ? monaco.editor.createModel('', 'plaintext')
                    : this.createFallbackModel('', 'plaintext');
                sourcePane.editor.setModel(emptyModel);
            }
        }

        // Añadir a destino
        if (!destPane.tabs.includes(path)) {
            destPane.tabs.push(path);
        }

        this.setActiveTabInPane(toCol, path);
        this.setActivePane(toCol);
        this.renderTabs();
        this.saveLayoutState();
        this.saveSessionState();

        const nombre = path.split('/').pop();
        if (window.layoutMgr && window.layoutMgr.mensajeEstado) {
            window.layoutMgr.mensajeEstado(`Movido: "${nombre}" al panel ${toCol + 1}`, 1800);
        }
    }

    /** Abre el archivo activo al lado (Ctrl+\) */
    splitRight(path = null) {
        let currentPath = path || this.activePath;
        if (!currentPath && this.openTabs.size > 0) {
            currentPath = Array.from(this.openTabs.keys())[0];
        }
        if (!currentPath) {
            if (window.layoutMgr && window.layoutMgr.mensajeEstado) {
                window.layoutMgr.mensajeEstado('Abre un archivo antes de dividir', 2000);
            }
            return;
        }

        const tab = this.openTabs.get(currentPath);
        const fileName = tab ? tab.name : currentPath.split('/').pop();

        if (this.numColumns === 1) {
            this.setColumnLayout(2, false);
            this.openFile(currentPath, fileName, tab ? tab.savedContent : '', tab ? tab.notebookData : null, 1);
            this.setActivePane(1);
        } else if (this.numColumns === 2) {
            if (this.activeCol === 0) {
                this.openFile(currentPath, fileName, tab ? tab.savedContent : '', tab ? tab.notebookData : null, 1);
                this.setActivePane(1);
            } else {
                this.setColumnLayout(3, false);
                this.openFile(currentPath, fileName, tab ? tab.savedContent : '', tab ? tab.notebookData : null, 2);
                this.setActivePane(2);
            }
        } else {
            // Ya hay 3 columnas: abrir en la siguiente columna cíclica
            const nextCol = (this.activeCol + 1) % 3;
            this.openFile(currentPath, fileName, tab ? tab.savedContent : '', tab ? tab.notebookData : null, nextCol);
            this.setActivePane(nextCol);
        }

        if (window.layoutMgr && window.layoutMgr.mensajeEstado) {
            window.layoutMgr.mensajeEstado(`Abierto al lado: ${fileName}`, 1800);
        }
    }

    /** Nivel de transparencia guardado (0 a 100) */
    obtenerNivelTransparencia() {
        const guardado = localStorage.getItem('prig_editor_transparencia');
        if (guardado !== null) {
            const num = parseInt(guardado, 10);
            return isNaN(num) ? 0 : Math.max(0, Math.min(100, num));
        }
        return localStorage.getItem('prig_editor_transparente') === '1' ? 100 : 0;
    }

    /** Indica si el fondo del código tiene algún grado de transparencia */
    esFondoTransparente() {
        return (this.nivelTransparencia || 0) > 0;
    }

    /** Alterna entre 0% y el último valor positivo (o 100%) */
    alternarFondoTransparente() {
        if (this.esFondoTransparente()) {
            this._ultimoNivelPositivo = this.nivelTransparencia;
            this.establecerNivelTransparencia(0);
        } else {
            const restaurar = this._ultimoNivelPositivo && this._ultimoNivelPositivo > 0 ? this._ultimoNivelPositivo : 100;
            this.establecerNivelTransparencia(restaurar);
        }
        if (window.layoutMgr && typeof window.layoutMgr.mensajeEstado === 'function') {
            window.layoutMgr.mensajeEstado(
                this.esFondoTransparente()
                    ? `Fondo de código: ${this.nivelTransparencia}% de transparencia`
                    : 'Fondo de código opaco restaurado (0%)',
                2200
            );
        }
    }

    /** Establece el nivel de transparencia del editor (0 a 100) */
    establecerNivelTransparencia(porcentaje) {
        const p = Math.max(0, Math.min(100, parseInt(porcentaje, 10) || 0));
        this.nivelTransparencia = p;
        this.fondoTransparente = p > 0;
        try {
            localStorage.setItem('prig_editor_transparencia', String(p));
            localStorage.setItem('prig_editor_transparente', this.fondoTransparente ? '1' : '0');
        } catch (e) {}

        const alpha = ((100 - p) / 100).toFixed(3);
        document.documentElement.style.setProperty('--editor-bg-alpha', String(alpha));
        document.body.classList.toggle('editor-transparente', this.fondoTransparente);

        // Forzar tema transparente o restaurar en Monaco
        if (typeof monaco !== 'undefined' && monaco.editor) {
            if (window.sintaxisMgr && typeof window.sintaxisMgr.aplicar === 'function') {
                window.sintaxisMgr.aplicar();
            } else {
                const tema = this.fondoTransparente
                    ? 'prig-transparent'
                    : (localStorage.getItem('prig_editor_theme') || 'vs-dark');
                try {
                    monaco.editor.setTheme(tema);
                } catch (e) {}
            }
            this.panes.forEach(pane => {
                if (pane && pane.editor && typeof pane.editor.updateOptions === 'function') {
                    pane.editor.updateOptions({
                        theme: this.fondoTransparente
                            ? (window.sintaxisMgr ? ('prig-custom-syntax-v' + (window.sintaxisMgr._temaVersion || 1)) : 'prig-transparent')
                            : (window.sintaxisMgr ? 'prig-custom-syntax' : (localStorage.getItem('prig_editor_theme') || 'vs-dark'))
                    });
                }
            });
        }

        window.dispatchEvent(new CustomEvent('prig:editor-transparencia-cambiada', {
            detail: { porcentaje: p, transparente: this.fondoTransparente, alpha: parseFloat(alpha) }
        }));
    }

    /** Compatibilidad: aplica fondo transparente con booleano o porcentaje */
    aplicarFondoTransparente(activo) {
        if (typeof activo === 'number') {
            this.establecerNivelTransparencia(activo);
        } else {
            this.establecerNivelTransparencia(activo ? (this.nivelTransparencia || 100) : 0);
        }
    }

    /** Cierra la vista del editor y vuelve a Inicio o a la vista siguiente */
    cerrarVistaEditor() {
        if (this.openTabs.size > 0) {
            let tieneSucios = false;
            for (const [p] of this.openTabs) {
                if (this.isDirty(p)) {
                    tieneSucios = true;
                    break;
                }
            }
            if (tieneSucios) {
                if (!confirm('Hay archivos con cambios sin guardar en el editor.\n\n¿Cerrar el editor de todos modos?')) {
                    return;
                }
            }
        }
        if (window.workArea && typeof window.workArea.cerrar === 'function') {
            window.workArea.cerrar('editor');
        }
    }

    /** Dibuja el estado vacío cuando no hay archivos abiertos */
    pintarVacio() {
        const vacio = document.getElementById('editor-vacio');
        const wrapper = document.getElementById('editor-area-wrapper');
        const gridEl = document.getElementById('editor-grid-container');
        const panelRaz = document.getElementById('editor-panel-razonamiento');
        const sinArchivos = this.openTabs.size === 0;

        if (vacio) vacio.hidden = !sinArchivos;
        // Ocultar el wrapper completo y el panel de razonamiento para que no quede el plano residual de color
        if (wrapper) wrapper.style.display = sinArchivos ? 'none' : 'flex';
        if (gridEl) gridEl.style.display = sinArchivos ? 'none' : 'flex';
        if (panelRaz && sinArchivos) panelRaz.style.display = 'none';
        else if (panelRaz && !panelRaz.classList.contains('oculto')) panelRaz.style.display = 'flex';

        if (vacio && !vacio.dataset.conectado) {
            vacio.dataset.conectado = '1';
            vacio.addEventListener('click', (e) => {
                const b = e.target.closest('[data-cmd]');
                if (!b) return;
                const cmd = b.dataset.cmd;
                if (cmd === 'editor.cerrar') {
                    this.cerrarVistaEditor();
                } else if (cmd === 'herr.inicio') {
                    if (window.Inicio && typeof window.Inicio.abrir === 'function') {
                        window.Inicio.abrir();
                    } else if (window.PrigCommands) {
                        window.PrigCommands.ejecutar('herr.inicio');
                    }
                } else if (window.PrigCommands) {
                    window.PrigCommands.ejecutar(cmd);
                }
            });
        }
    }

    /** Renderiza las pestañas de todas las columnas visibles */
    renderTabs() {
        this.pintarVacio();
        for (let i = 0; i < 3; i++) {
            this.renderTabsForPane(i);
        }
    }

    /** Renderiza las pestañas de una columna específica */
    renderTabsForPane(colIndex) {
        const container = document.getElementById(colIndex === 0 ? 'editor-tabs' : `editor-tabs-${colIndex}`);
        if (!container) return;

        container.innerHTML = '';
        const pane = this.panes[colIndex];
        const tabsList = pane.tabs || [];

        // Gestionar estado vacío en columnas secundarias
        const emptyEl = document.getElementById(`editor-col-empty-${colIndex}`);
        const monacoEl = document.getElementById(colIndex === 0 ? 'monaco-editor-container' : `monaco-editor-container-${colIndex}`);
        if (colIndex > 0 && emptyEl) {
            if (tabsList.length === 0) {
                emptyEl.style.display = 'flex';
                if (monacoEl) monacoEl.style.display = 'none';
            } else {
                emptyEl.style.display = 'none';
                if (monacoEl) {
                    monacoEl.style.display = '';
                    this.panes[colIndex].editor?.layout();
                }
            }
        }

        tabsList.forEach(path => {
            const tab = this.openTabs.get(path);
            if (!tab) return;

            const tabEl = document.createElement('div');
            tabEl.className = `tab-item ${path === pane.activePath ? 'active' : ''}`;
            tabEl.dataset.path = path;
            tabEl.dataset.col = colIndex;
            tabEl.title = path;
            tabEl.draggable = true;

            const icon = tab.isNotebook ? '<i class="fa-solid fa-book-bookmark" style="color:var(--accent-yellow); font-size:11px;"></i>' : '';
            const dirty = this.isDirty(path);

            tabEl.innerHTML = `
                ${icon}
                <span class="tab-name"></span>
                <span class="tab-dirty" title="Cambios sin guardar"${dirty ? '' : ' hidden'}>●</span>
                <i class="fa-solid fa-xmark tab-close"></i>
            `;

            tabEl.querySelector('.tab-name').textContent = tab.name;
            tabEl.querySelector('.tab-close').onclick = (event) => this.closeTabInPane(colIndex, path, event);
            tabEl.onclick = () => {
                this.setActiveTabInPane(colIndex, path);
                this.setActivePane(colIndex);
            };

            // Clic central para cerrar
            tabEl.onauxclick = (event) => {
                if (event.button === 1) this.closeTabInPane(colIndex, path, event);
            };

            // Drag and drop events en la pestaña de código
            tabEl.ondragstart = (e) => {
                e.dataTransfer.setData('application/prig-code-tab', JSON.stringify({ path, colIndex }));
                tabEl.classList.add('arrastrando');
            };

            tabEl.ondragend = () => {
                tabEl.classList.remove('arrastrando');
            };

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

    /** Marca la pestaña como guardada tras una confirmación del backend */
    markSaved(path, content = null) {
        const tab = this.openTabs.get(path);
        if (!tab) return;
        tab.savedContent = content !== null ? content : tab.model.getValue();
        this.renderTabs();
    }

    /** Una pestaña pasa a apuntar a otra ruta (renombrar o mover archivo) */
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

        this.panes.forEach(p => {
            p.tabs = p.tabs.map(t => t === anterior ? nueva : t);
            if (p.activePath === anterior) p.activePath = nueva;
        });

        this.renderTabs();
        this.saveLayoutState();
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

    /** Contenido REAL del archivo activo en disco */
    getContent() {
        return this.editor ? this.editor.getValue() : '';
    }

    /** Contenido legible para enviar como contexto a la IA */
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

    /** Obtiene la sintaxis de comentarios según el lenguaje */
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
                return { prefix: '// ', suffix: '' };
        }
    }

    /** Convierte automáticamente "Prig//:" en un comentario */
    checkAutoComment(path) {
        if (this._isAutoCommenting || !this.editor) return;
        const tab = this.openTabs.get(path);
        if (!tab || !tab.model) return;
        const model = tab.model;
        const position = this.editor.getPosition();
        if (!position) return;

        const lineNumber = position.lineNumber;
        const lineContent = model.getLineContent(lineNumber);

        const idx = lineContent.search(/Prig\/\/:/i);
        if (idx === -1) return;

        const before = lineContent.substring(0, idx);
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

    /** Ejecuta una instrucción de prompt en línea "Prig//: <instrucción>" */
    async executeInlinePrompt(lineNumber, promptText = null, targetEditor = null) {
        const edInstance = targetEditor || this.editor;
        if (!edInstance) return;
        const model = edInstance.getModel();
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
        const fullContent = model.getValue();

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

        const placeholderText = `${indent}${comment.prefix}[⏳ Prig IA generando código...]${comment.suffix}`;
        const insertRange = new monaco.Range(lineNumber + 1, 1, lineNumber + 1, 1);

        edInstance.executeEdits('prig-inline', [{
            range: insertRange,
            text: placeholderText + '\n',
            forceMoveMarkers: true
        }]);

        const placeholderLine = lineNumber + 1;
        const modelSelect = document.getElementById('model-select') || document.getElementById('ai-model-select');
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
                    if (typeof errData.detail === 'string') detailMsg = errData.detail;
                    else if (Array.isArray(errData.detail)) detailMsg = errData.detail.map(d => d.msg || JSON.stringify(d)).join(', ');
                } catch (e) {}
                throw new Error(detailMsg);
            }

            const data = await res.json();
            const generatedCode = (data.code || '').trimEnd();

            const replaceRange = new monaco.Range(
                placeholderLine, 1,
                placeholderLine, model.getLineMaxColumn(placeholderLine)
            );

            edInstance.executeEdits('prig-inline', [{
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
                placeholderLine, 1,
                placeholderLine, model.getLineMaxColumn(placeholderLine)
            );
            edInstance.executeEdits('prig-inline', [{
                range: replaceRange,
                text: `${indent}${comment.prefix}[❌ Error Prig IA: ${err.message}]${comment.suffix}`,
                forceMoveMarkers: true
            }]);
            if (window.terminalMgr) {
                window.terminalMgr.appendLine(`[Prig IA Error] ${err.message}`, 'stderr');
            }
        }
    }

    /** Guarda la disposición de columnas en localStorage */
    saveLayoutState() {
        const layout = {
            numColumns: this.numColumns,
            activeCol: this.activeCol,
            colWidths: this.colWidths,
            panes: this.panes.map(p => ({
                tabs: p.tabs,
                activePath: p.activePath
            }))
        };
        localStorage.setItem('prig_editor_layout_state', JSON.stringify(layout));
    }

    /** Restaura la disposición de columnas guardada */
    restoreLayoutState() {
        try {
            const raw = localStorage.getItem('prig_editor_layout_state');
            if (!raw) return;
            const state = JSON.parse(raw);
            if (!state) return;

            if (state.colWidths && Array.isArray(state.colWidths)) {
                this.colWidths = state.colWidths;
            }

            if (state.numColumns && state.numColumns >= 1 && state.numColumns <= 3) {
                this.setColumnLayout(state.numColumns, false);
            }

            if (state.activeCol !== undefined) {
                this.activeCol = state.activeCol;
            }
        } catch (e) {
            console.error('Error restaurando disposición de columnas:', e);
        }
    }

    /** Guarda la sesión de archivos abiertos */
    saveSessionState() {
        const state = {
            activePath: this.activePath,
            activeCol: this.activeCol,
            numColumns: this.numColumns,
            tabs: Array.from(this.openTabs.values()).map(tab => ({
                path: tab.path,
                name: tab.name
            })),
            panesTabs: this.panes.map(p => ({
                tabs: p.tabs,
                activePath: p.activePath
            }))
        };
        localStorage.setItem('prig_ide_session', JSON.stringify(state));
    }

    /** Restaura la sesión de archivos abiertos */
    async restoreSessionState() {
        try {
            const savedStr = localStorage.getItem('prig_ide_session');
            if (!savedStr) return;
            const state = JSON.parse(savedStr);
            if (!state || !state.tabs) return;
            this._restaurando = true;

            // Abrir cada archivo
            for (const tab of state.tabs) {
                try {
                    const res = await fetch(`/api/file?path=${encodeURIComponent(tab.path)}`);
                    const data = await res.json();
                    if (data.content !== undefined) {
                        // Determinar a qué columna pertenecía
                        let targetCol = 0;
                        if (state.panesTabs && Array.isArray(state.panesTabs)) {
                            state.panesTabs.forEach((pt, ci) => {
                                if (pt.tabs && pt.tabs.includes(tab.path)) targetCol = ci;
                            });
                        }
                        this.openFile(tab.path, tab.name, data.content, data.notebook_data, targetCol);
                    }
                } catch (e) {
                    console.error('Error al restaurar tab:', tab.path, e);
                }
            }

            // Restaurar pestaña activa de cada columna
            if (state.panesTabs && Array.isArray(state.panesTabs)) {
                state.panesTabs.forEach((pt, ci) => {
                    if (pt.activePath && this.openTabs.has(pt.activePath)) {
                        this.setActiveTabInPane(ci, pt.activePath);
                    }
                });
            }

            if (state.activeCol !== undefined) {
                this.setActivePane(state.activeCol);
            }
        } catch (e) {
            console.error('Error leyendo estado de sesion:', e);
        } finally {
            this._restaurando = false;
        }
    }

    insertText(text) {
        if (!this.editor) return;
        const position = this.editor.getPosition();
        if (position && typeof monaco !== 'undefined') {
            this.editor.executeEdits('prig-insert', [{
                range: new monaco.Range(position.lineNumber, position.column, position.lineNumber, position.column),
                text: text
            }]);
        } else {
            const val = this.editor.getValue();
            this.editor.setValue(val ? val + '\n' + text : text);
        }
        this.editor.focus();
    }
}

window.editorMgr = new EditorManager();

// Red de seguridad: advertir antes de cerrar la ventana con cambios sin guardar
window.addEventListener('beforeunload', (e) => {
    if (window.__prigSinAvisoAlSalir) return;
    if (window.editorMgr && window.editorMgr.hasUnsavedChanges()) {
        e.preventDefault();
        e.returnValue = '';
        return '';
    }
});
