class NotebookViewManager {
    constructor() {
        this.container = null;
        this.activeNotebookPath = null;
        this.cellsData = [];
    }

    init(containerEl) {
        this.container = containerEl;
    }

    renderNotebook(notebookData) {
        if (!this.container) return;
        this.activeNotebookPath = notebookData.path;
        this.activeNotebookName = notebookData.name || '';
        this.cellsData = notebookData.cells || [];
        this.dirty = false;

        this.container.innerHTML = '';
        this.container.className = 'notebook-view-active';

        const header = document.createElement('div');
        header.className = 'nb-header';
        header.innerHTML = `
            <div class="nb-title"><i class="fa-solid fa-book-bookmark"></i> <span class="nb-title-text"></span>
                <span class="nb-dirty-badge" hidden title="Cambios sin guardar — Ctrl+S">●</span>
            </div>
            <div class="nb-actions" style="display:flex; gap:8px;">
                <button class="tool-btn btn-primary" onclick="window.notebookMgr.runAllCells()">
                    <i class="fa-solid fa-play"></i> Ejecutar
                </button>
                <button class="tool-btn" style="background:rgba(249,226,175,0.2); color:var(--accent-yellow); border-color:rgba(249,226,175,0.4);" onclick="window.notebookMgr.restartSession()" title="Borra todas las variables y reinicia el intérprete del cuaderno">
                    <i class="fa-solid fa-arrows-rotate"></i> Reiniciar
                </button>
                <button class="tool-btn" style="background:rgba(203,166,247,0.2); color:var(--accent-purple); border-color:rgba(203,166,247,0.4);" onclick="window.notebookMgr.explainEntireNotebook()">
                    <i class="fa-solid fa-brain"></i> Analizar
                </button>
                <button class="tool-btn" style="background:rgba(231,76,60,0.2); color:#e74c3c; border-color:rgba(231,76,60,0.4);" onclick="window.pdfExporterMgr.openForSingleFile('${(notebookData.path || '').replace(/'/g, "\\'")}')">
                    <i class="fa-solid fa-file-pdf"></i> PDF
                </button>
            </div>
        `;
        header.querySelector('.nb-title-text').textContent = notebookData.name || '';
        this.container.appendChild(header);

        const listContainer = document.createElement('div');
        listContainer.className = 'nb-cells-list';

        this.cellsData.forEach((cell, idx) => {
            const cellCard = document.createElement('div');
            cellCard.className = `nb-cell-card cell-${cell.type}`;
            cellCard.id = `cell-card-${idx}`;

            if (cell.type === 'markdown') {
                cellCard.innerHTML = `
                    <div class="nb-cell-header">
                        <span class="nb-cell-tag"><i class="fa-solid fa-align-left"></i> Markdown</span>
                        <div class="nb-cell-actions">
                            <button title="Explicar con IA" onclick="window.notebookMgr.explainCell(${idx})">
                                <i class="fa-solid fa-lightbulb"></i> Explicar
                            </button>
                        </div>
                    </div>
                    <div class="nb-cell-markdown-body" data-idx="${idx}" title="Doble clic para editar">${this.formatMarkdown(cell.source)}</div>
                `;
            } else {
                const outputsHtml = cell.outputs && cell.outputs.length > 0 ? this.renderOutputsHtml(cell.outputs) : '';
                cellCard.innerHTML = `
                    <div class="nb-cell-header">
                        <span class="nb-cell-tag"><i class="fa-brands fa-python"></i> In [${cell.execution_count || idx}]:</span>
                        <div class="nb-cell-actions">
                            <button title="Ejecutar Celda (Shift+Enter)" class="btn-run-cell" onclick="window.notebookMgr.runSingleCell(${idx})">
                                <i class="fa-solid fa-play"></i> Ejecutar Celda
                            </button>
                            <button title="Explicar Lógica con IA" onclick="window.notebookMgr.explainCell(${idx})">
                                <i class="fa-solid fa-diagram-project"></i> Explicar Lógica
                            </button>
                        </div>
                    </div>
                    <div class="nb-cell-code-body">
                        <pre class="nb-code-editable" contenteditable="plaintext-only" spellcheck="false"
                             data-idx="${idx}" role="textbox" aria-label="Celda de código ${idx + 1}"></pre>
                    </div>
                    <div class="nb-cell-output-container" id="nb-output-${idx}" style="${outputsHtml ? 'display:block;' : 'display:none;'}">
                        ${outputsHtml}
                    </div>
                `;
            }
            listContainer.appendChild(cellCard);

            // textContent, no interpolación: el código de la celda puede contener
            // `<` o comillas y romper el marcado si se inyecta como HTML.
            const editable = cellCard.querySelector('.nb-code-editable');
            if (editable) {
                editable.textContent = cell.source;
                editable.addEventListener('input', () => this.onCellEdited(idx, editable.textContent));
                editable.addEventListener('keydown', (e) => this.onCellKeydown(e, idx));
            }

            const md = cellCard.querySelector('.nb-cell-markdown-body');
            if (md) md.addEventListener('dblclick', () => this.editMarkdownCell(idx, md));
        });

        this.container.appendChild(listContainer);
    }

    /** Añade una celda al final (lo usa «Insertar en Editor / Notebook» del chat) */
    addCell(tipo, fuente) {
        if (!this.activeNotebookPath) return false;
        this.cellsData.push({ type: tipo === 'markdown' ? 'markdown' : 'code', source: fuente || '', outputs: [] });
        this.renderNotebook({ path: this.activeNotebookPath, name: this.activeNotebookName, cells: this.cellsData });
        this.dirty = true;
        this.markNotebookDirty();
        const ultima = document.getElementById(`cell-card-${this.cellsData.length - 1}`);
        if (ultima) ultima.scrollIntoView({ block: 'center' });
        return true;
    }

    /** Una celda editada marca el cuaderno como modificado, igual que el editor */
    onCellEdited(idx, texto) {
        if (!this.cellsData[idx]) return;
        this.cellsData[idx].source = texto;
        this.dirty = true;
        this.markNotebookDirty();
    }

    /** Tabulador inserta indentación en vez de saltar de elemento */
    onCellKeydown(e, idx) {
        if (e.key === 'Tab') {
            e.preventDefault();
            document.execCommand('insertText', false, '    ');
            return;
        }
        // Ctrl+Enter ejecuta la celda, como en Jupyter
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            e.preventDefault();
            this.runSingleCell(idx);
        }
    }

    editMarkdownCell(idx, contenedor) {
        const cell = this.cellsData[idx];
        if (!cell || contenedor.dataset.editing === '1') return;

        const area = document.createElement('textarea');
        area.value = cell.source;
        area.className = 'nb-md-editor';
        area.setAttribute('aria-label', `Celda markdown ${idx + 1}`);
        contenedor.dataset.editing = '1';
        contenedor.replaceWith(area);
        area.focus();

        const cerrar = () => {
            cell.source = area.value;
            this.dirty = true;
            this.markNotebookDirty();
            contenedor.innerHTML = this.formatMarkdown(cell.source);
            contenedor.dataset.editing = '0';
            area.replaceWith(contenedor);
        };
        area.addEventListener('blur', cerrar);
        area.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') { e.preventDefault(); cerrar(); }
        });
    }

    /**
     * Vuelca las celdas al modelo del editor en formato nbformat.
     *
     * El guardado escribe lo que hay en el editor Monaco, así que editar celdas
     * tiene que actualizar ese JSON o los cambios no llegarían nunca al archivo.
     */
    markNotebookDirty() {
        const indicador = document.querySelector('.nb-dirty-badge');
        if (indicador) indicador.hidden = false;

        if (!window.editorMgr || !this.activeNotebookPath) return;
        const tab = window.editorMgr.openTabs.get(this.activeNotebookPath);
        if (!tab) return;

        try {
            const nb = JSON.parse(tab.model.getValue());
            nb.cells = this.cellsData.map((c, i) => {
                const original = (nb.cells && nb.cells[i]) ? nb.cells[i] : {};
                return Object.assign({}, original, {
                    cell_type: c.type === 'markdown' ? 'markdown' : 'code',
                    source: c.source.split(/(?<=\n)/),
                    metadata: original.metadata || {},
                    ...(c.type === 'markdown' ? {} : {
                        outputs: original.outputs || [],
                        execution_count: original.execution_count ?? null
                    })
                });
            });
            tab.model.setValue(JSON.stringify(nb, null, 2));
        } catch (e) {
            console.error('No se pudo sincronizar el cuaderno:', e);
        }
    }

    renderOutputsHtml(outputs) {
        return outputs.map(out => {
            if (out.type === 'error') {
                return `<div class="nb-output-line stderr">${this.escapeHtml(out.text)}</div>`;
            } else if (out.type === 'html') {
                return `<div class="nb-output-line html-output">${this.sanitize(out.text)}</div>`;
            } else if (out.type === 'image') {
                const cleanBase64 = out.data.replace(/[\r\n\s]/g, '');
                const mime = out.mime || 'image/png';
                if (mime.includes('svg')) {
                    return `<div class="nb-output-line svg-output">${this.sanitize(out.data)}</div>`;
                }
                return `<img src="data:${mime};base64,${cleanBase64}" style="max-width:100%; height:auto;" />`;
            }
            return `<div class="nb-output-line stdout">${this.escapeHtml(out.text)}</div>`;
        }).join('');
    }

    formatMarkdown(text) {
        let html = '';
        if (typeof marked !== 'undefined') {
            try {
                html = marked.parse(text);
            } catch (e) {
                console.error("Marked error:", e);
                html = text;
            }
        } else {
            html = text;
            html = html.replace(/^# (.*$)/gim, '<h1 class="nb-h1">$1</h1>');
            html = html.replace(/^## (.*$)/gim, '<h2 class="nb-h2">$1</h2>');
            html = html.replace(/^### (.*$)/gim, '<h3 class="nb-h3">$1</h3>');
            html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
            html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
            html = html.replace(/\n/g, '<br>');
        }

        // Reescribir rutas de imágenes locales o relativas a la API raw-file
        html = html.replace(/<img\s+([^>]*?)src=["'](?!data:|http:\/\/|https:\/\/|\/\/)([^"']+)["']([^>]*?)>/gi, (match, p1, src, p2) => {
            return `<img ${p1}src="/api/raw-file?path=${encodeURIComponent(src)}"${p2}>`;
        });

        // Reescribir citas de libros ::cite[id] a Tarjetas de Cita Interactivas
        html = html.replace(/::cite\[([^\]]+)\]/gi, (match, citeId) => {
            return `
                <div class="book-cite-card" style="border-left: 3px solid var(--accent-purple); background: rgba(203,166,247,0.1); padding: 10px 14px; border-radius: 4px; margin: 10px 0; font-size: 13px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 4px;">
                        <span style="font-weight:600; color:var(--accent-purple);"><i class="fa-solid fa-quote-left"></i> Cita de Libro (${citeId})</span>
                        <button class="tool-btn" style="font-size:10px; padding:2px 6px;" onclick="if(window.bookLibraryMgr){ window.bookLibraryMgr.openModal(); }"><i class="fa-solid fa-book-open"></i> Abrir Lector</button>
                    </div>
                </div>
            `;
        });

        if (typeof DOMPurify !== 'undefined') {
            // El markdown de un cuaderno puede traer HTML arbitrario del autor original
            html = DOMPurify.sanitize(html, { USE_PROFILES: { html: true, svg: true, mathMl: true } });
        }

        return html;
    }

    /** Sanea HTML procedente del cuaderno antes de inyectarlo */
    sanitize(html) {
        const value = String(html ?? '');
        if (typeof DOMPurify !== 'undefined') {
            return DOMPurify.sanitize(value, { USE_PROFILES: { html: true, svg: true, mathMl: true } });
        }
        return this.escapeHtml(value);
    }

    escapeHtml(text) {
        return String(text ?? '')
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");
    }

    async runSingleCell(idx) {
        const cell = this.cellsData[idx];
        if (!cell || cell.type !== 'code') return true;

        const outputEl = document.getElementById(`nb-output-${idx}`);
        outputEl.style.display = 'block';
        outputEl.innerHTML = '<div class="nb-output-line info">Ejecutando celda...</div>';

        try {
            const res = await fetch('/api/notebook/cell/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code: cell.source, path: this.activeNotebookPath })
            });
            const data = prigJson(res);
            
            outputEl.innerHTML = '';
            if (data.stdout) {
                outputEl.innerHTML += `<div class="nb-output-line stdout">${this.escapeHtml(data.stdout)}</div>`;
            }
            if (data.stderr) {
                outputEl.innerHTML += `<div class="nb-output-line stderr">${this.escapeHtml(data.stderr)}</div>`;
            }
            if (!data.stdout && !data.stderr) {
                outputEl.innerHTML = `<div class="nb-output-line info">[Celda finalizada en ${data.elapsed}s sin salida visual]</div>`;
            }
            return data.success !== false;
        } catch (e) {
            outputEl.innerHTML = `<div class="nb-output-line stderr">Error al ejecutar celda: ${this.escapeHtml(String(e))}</div>`;
            return false;
        }
    }

    async runAllCells() {
        for (let i = 0; i < this.cellsData.length; i++) {
            if (this.cellsData[i].type !== 'code') continue;
            const ok = await this.runSingleCell(i);
            if (!ok) {
                // Detenerse en el primer fallo: las celdas siguientes dependen de esta
                break;
            }
        }
    }

    /** Reinicia el intérprete del cuaderno, descartando todas sus variables */
    async restartSession() {
        try {
            await prigJson(await fetch('/api/notebook/session/reset', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: this.activeNotebookPath })
            }));
            this.cellsData.forEach((cell, idx) => {
                const outputEl = document.getElementById(`nb-output-${idx}`);
                if (outputEl) {
                    outputEl.innerHTML = '';
                    outputEl.style.display = 'none';
                }
            });
            if (window.terminalMgr) {
                window.terminalMgr.appendLine('[Sesión del cuaderno reiniciada: se borraron todas las variables]', 'info');
            }
        } catch (e) {
            alert(`No se pudo reiniciar la sesión del cuaderno: ${e.message}`);
        }
    }

    explainCell(idx) {
        const cell = this.cellsData[idx];
        if (!cell) return;
        if (window.aiChatMgr) {
            window.aiChatMgr.sendMessage(
                `Explícame el FLUJO DE EJECUCIÓN paso a paso de esta celda de Jupyter Notebook:`,
                "explain_flow",
                cell.source
            );
        }
    }

    explainEntireNotebook() {
        if (!this.cellsData || this.cellsData.length === 0) {
            alert('El cuaderno está vacío.');
            return;
        }

        const fullContent = this.cellsData.map((cell, idx) => {
            return `--- [CELDA ${idx + 1} - ${cell.type.toUpperCase()}] ---\n${cell.source}`;
        }).join('\n\n');

        if (window.aiChatMgr) {
            window.aiChatMgr.sendMessage(
                `Realiza un ANÁLISIS INTEGRAL Y COMPLETO de todo este cuaderno Jupyter Notebook. Explica el objetivo principal, la arquitectura, el flujo de ejecución entre celdas, los hallazgos y sugerencias de optimización:`,
                "explain",
                fullContent
            );
        }
    }
}

window.notebookMgr = new NotebookViewManager();
