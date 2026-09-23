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

            // Enlazar contenedores DOM de cada panel
            this.panes[0].containerEl = document.getElementById('monaco-editor-container');
            this.panes[0].tabsEl = document.getElementById('editor-tabs');

            this.panes[1].containerEl = document.getElementById('monaco-editor-container-1');
            this.panes[1].tabsEl = document.getElementById('editor-tabs-1');

            this.panes[2].containerEl = document.getElementById('monaco-editor-container-2');
            this.panes[2].tabsEl = document.getElementById('editor-tabs-2');

            // Instancia principal de Monaco (Col 0)
            this.panes[0].editor = this.createMonacoInstance(this.panes[0].containerEl, 0);

            // Iniciar cuaderno Jupyter
            if (window.notebookMgr) {
                window.notebookMgr.init(document.getElementById('notebook-view-container'));
            }

            // Iniciar controles de disposición y divisores redimensionables
            this.initLayoutControls();
            this.setupResizers();
            this.setupTabDragAndDrop();

            this.pintarVacio();

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

            // Restaurar disposición y sesión
            this.restoreLayoutState();
            this.restoreSessionState();
        });
    }

    /** Crea una instancia de Monaco Editor para una columna dada */
    createMonacoInstance(containerEl, colIndex) {
        if (!containerEl || typeof monaco === 'undefined') return null;

        const ed = monaco.editor.create(containerEl, {
            value: '',
            language: 'python',
            theme: localStorage.getItem('prig_editor_theme') || 'prig-dark',
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

        // Atajo Ctrl+S
        ed.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
            if (window.app) window.app.saveCurrentFile();
        });

        // Atajo Ctrl+\ (dividir al lado)
        ed.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Backslash, () => {
            this.splitRight();
        });

        // Atajo Ctrl+Enter: prompt en línea o ejecutar código
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
            if (window.app) window.app.runCode();
        });

        window.dispatchEvent(new CustomEvent('prig:editor-creado', { detail: { editor: ed, principal: (colIndex === 0) } }));
        return ed;
    }

    /** Obtiene o inicializa de forma perezosa el editor de una columna secundaria */
    getOrCreatePaneEditor(colIndex) {
        if (colIndex < 0 || colIndex >= 3) return null;
        if (!this.panes[colIndex].editor) {
            this.panes[colIndex].editor = this.createMonacoInstance(this.panes[colIndex].containerEl, colIndex);
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

            // Si Col 1 no tiene pestañas y Col 0 tiene varias, mover una o clonar la activa
            if (this.panes[1].tabs.length === 0 && this.panes[0].tabs.length > 1) {
                const moverRuta = this.panes[0].tabs[this.panes[0].tabs.length - 1];
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

            // Si Col 2 no tiene pestañas, poblar con archivo actual
            if (this.panes[2].tabs.length === 0 && this.activePath) {
                this.openFileInPane(2, this.activePath);
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

    /** Configura drag & drop para mover pestañas entre columnas */
    setupTabDragAndDrop() {
        [0, 1, 2].forEach(colIndex => {
            const tabsEl = document.getElementById(colIndex === 0 ? 'editor-tabs' : `editor-tabs-${colIndex}`);
            const colEl = document.getElementById(`editor-col-${colIndex}`);

            const zonas = [tabsEl, colEl].filter(Boolean);
            zonas.forEach(zona => {
                zona.addEventListener('dragover', (e) => {
                    e.preventDefault();
                    e.dataTransfer.dropEffect = 'move';
                    if (tabsEl) tabsEl.classList.add('drag-over');
                });

                zona.addEventListener('dragleave', (e) => {
                    if (tabsEl && (!e.relatedTarget || !zona.contains(e.relatedTarget))) {
                        tabsEl.classList.remove('drag-over');
                    }
                });

                zona.addEventListener('drop', (e) => {
                    e.preventDefault();
                    if (tabsEl) tabsEl.classList.remove('drag-over');
                    const rawData = e.dataTransfer.getData('application/prig-tab') || e.dataTransfer.getData('text/plain');
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
                        console.error('Error procesando drop de pestaña:', err);
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
        if (!this.panes[0].editor) return;

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
            const tab = { name, path, model, isNotebook, notebookData, savedContent: content };
            this.openTabs.set(path, tab);

            model.onDidChangeContent(() => {
                this.checkAutoComment(tab.path);
                this.onContentChanged(tab.path);
            });
        } else {
            const tab = this.openTabs.get(path);
            if (tab.model.getValue() !== content) {
                tab.model.setValue(content);
            }
            tab.savedContent = content;
            tab.notebookData = notebookData;
        }

        const destCol = targetCol !== null ? targetCol : this.activeCol;
        if (destCol >= this.numColumns) {
            this.setColumnLayout(destCol + 1, false);
        }

        const targetPane = this.panes[destCol];
        if (!targetPane.tabs.includes(path)) {
            targetPane.tabs.push(path);
        }

        this.setActiveTabInPane(destCol, path);
        this.setActivePane(destCol);
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

    /** Establece la pestaña activa en el panel actualmente enfocado (compatibilidad) */
    setActiveTab(path) {
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

        // Si la columna es 0 y es un cuaderno, manejar vista de cuaderno
        if (colIndex === 0) {
            const monacoContainer = document.getElementById('monaco-editor-container');
            const notebookContainer = document.getElementById('notebook-view-container');
            const viewModeBar = document.getElementById('view-mode-bar');

            if (tabData.isNotebook && tabData.notebookData) {
                if (viewModeBar) viewModeBar.style.display = 'flex';
                if (monacoContainer) monacoContainer.style.display = 'none';
                if (notebookContainer) {
                    notebookContainer.style.display = 'flex';
                    if (window.notebookMgr) window.notebookMgr.renderNotebook(tabData.notebookData);
                }
            } else {
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
            tabData.model.dispose();
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
                    pane.editor.setModel(monaco.editor.createModel('', 'plaintext'));
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
                sourcePane.editor.setModel(monaco.editor.createModel('', 'plaintext'));
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

    /** Dibuja el estado vacío cuando no hay archivos abiertos */
    pintarVacio() {
        const vacio = document.getElementById('editor-vacio');
        if (!vacio) return;
        const sinArchivos = this.openTabs.size === 0;
        vacio.hidden = !sinArchivos;

        const gridEl = document.getElementById('editor-grid-container');
        if (gridEl) gridEl.style.display = sinArchivos ? 'none' : 'flex';

        if (!vacio.dataset.conectado) {
            vacio.dataset.conectado = '1';
            vacio.addEventListener('click', (e) => {
                const b = e.target.closest('[data-cmd]');
                if (b && window.PrigCommands) window.PrigCommands.ejecutar(b.dataset.cmd);
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

            // Drag and drop events en la pestaña
            tabEl.ondragstart = (e) => {
                e.dataTransfer.setData('application/prig-tab', JSON.stringify({ path, colIndex }));
                e.dataTransfer.setData('text/plain', JSON.stringify({ path, colIndex }));
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
