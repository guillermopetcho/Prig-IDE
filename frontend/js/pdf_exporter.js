class PDFExporterManager {
    constructor() {
        this.currentFolderPath = null;
        this.currentFolderName = null;
        this.availableFiles = [];
        this.selectedFilePaths = new Set();
        this.activeTheme = 'light';
        this.options = {
            include_outputs: true,
            show_line_numbers: true,
            include_cover: true,
            font_size: '13px',
            page_size: 'a4'
        };
        this.previewDebounceTimer = null;
    }

    init() {
        this.modal = document.getElementById('modal-pdf-exporter');
        this.closeBtn = document.getElementById('btn-close-pdf-exporter');
        this.filesContainer = document.getElementById('pdf-files-checklist');
        this.previewFrame = document.getElementById('pdf-preview-iframe');
        this.folderTitleEl = document.getElementById('pdf-modal-folder-name');
        this.folderPathEl = document.getElementById('pdf-modal-folder-path');
        this.filesCountEl = document.getElementById('pdf-modal-files-count');

        if (this.closeBtn) {
            this.closeBtn.onclick = () => this.closeModal();
        }

        // Event listeners para opciones
        const bindInput = (id, key, isCheckbox = true) => {
            const el = document.getElementById(id);
            if (el) {
                el.onchange = () => {
                    this.options[key] = isCheckbox ? el.checked : el.value;
                    this.schedulePreviewUpdate();
                };
            }
        };

        bindInput('opt-pdf-outputs', 'include_outputs', true);
        bindInput('opt-pdf-linenos', 'show_line_numbers', true);
        bindInput('opt-pdf-cover', 'include_cover', true);
        bindInput('opt-pdf-fontsize', 'font_size', false);
        bindInput('opt-pdf-pagesize', 'page_size', false);
    }

    async openModal(folderPath, folderName) {
        if (!this.modal) this.init();
        this.currentFolderPath = folderPath;
        this.currentFolderName = folderName || folderPath.split('/').pop() || folderPath;

        if (this.folderTitleEl) this.folderTitleEl.textContent = this.currentFolderName;
        if (this.folderPathEl) this.folderPathEl.textContent = folderPath;

        this.modal.style.display = 'flex';
        this.filesContainer.innerHTML = '<div style="padding:20px; text-align:center; color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i> Escaneando archivos de código y notebooks...</div>';

        try {
            const res = await fetch(`/api/folder/code-files?path=${encodeURIComponent(folderPath)}`);
            const data = await res.json();
            
            if (data.error) {
                this.filesContainer.innerHTML = `<div style="padding:15px; color:var(--accent-red);">${data.error}</div>`;
                return;
            }

            this.availableFiles = data.files || [];
            this.selectedFilePaths = new Set(this.availableFiles.map(f => f.path));

            if (this.filesCountEl) {
                this.filesCountEl.textContent = `${this.availableFiles.length} detectados`;
            }

            this.renderFilesList();
            this.updatePreview();

        } catch (e) {
            console.error('Error cargando archivos para PDF:', e);
            this.filesContainer.innerHTML = `<div style="padding:15px; color:var(--accent-red);">Error al escanear carpeta: ${e}</div>`;
        }
    }

    async openForSingleFile(filePath) {
        const baseFolder = filePath.substring(0, filePath.lastIndexOf('/')) || '/';
        await this.openModal(baseFolder, 'Archivo Individual');
        this.selectedFilePaths = new Set([filePath]);
        this.renderFilesList();
        this.updatePreview();
    }

    closeModal() {
        if (this.modal) {
            this.modal.style.display = 'none';
        }
    }

    renderFilesList(filterSearch = '') {
        if (!this.filesContainer) return;
        this.filesContainer.innerHTML = '';

        if (this.availableFiles.length === 0) {
            this.filesContainer.innerHTML = '<div style="padding:20px; color:var(--text-muted); text-align:center;">No se encontraron notebooks (.ipynb) ni archivos de código en esta carpeta.</div>';
            return;
        }

        const filtered = this.availableFiles.filter(f => {
            if (!filterSearch) return true;
            return f.name.toLowerCase().includes(filterSearch.toLowerCase()) || f.rel_path.toLowerCase().includes(filterSearch.toLowerCase());
        });

        filtered.forEach(f => {
            const isChecked = this.selectedFilePaths.has(f.path);
            const itemEl = document.createElement('label');
            itemEl.className = `pdf-file-item ${isChecked ? 'selected' : ''}`;
            
            const iconClass = f.is_notebook ? 'fa-book-bookmark' : this.getFileIcon(f.name);
            const iconColor = f.is_notebook ? 'var(--accent-yellow)' : 'var(--accent-blue)';
            const metaBadge = f.is_notebook 
                ? `<span class="pdf-badge nb">${f.cells_count} celdas</span>` 
                : `<span class="pdf-badge code">${f.lines_count} líneas</span>`;

            itemEl.innerHTML = `
                <input type="checkbox" ${isChecked ? 'checked' : ''} onchange="window.pdfExporterMgr.toggleFile('${f.path}', this.checked)">
                <i class="fa-solid ${iconClass}" style="color:${iconColor}; margin-right:6px;"></i>
                <div class="pdf-file-info">
                    <span class="pdf-file-name">${f.name}</span>
                    <span class="pdf-file-sub">${f.rel_path}</span>
                </div>
                ${metaBadge}
            `;
            this.filesContainer.appendChild(itemEl);
        });
    }

    getFileIcon(filename) {
        const ext = filename.split('.').pop().toLowerCase();
        switch (ext) {
            case 'py': return 'fa-brands fa-python';
            case 'js': return 'fa-brands fa-js';
            case 'html': return 'fa-brands fa-html5';
            case 'css': return 'fa-brands fa-css3-alt';
            case 'json': return 'fa-solid fa-code';
            case 'md': return 'fa-solid fa-file-lines';
            case 'sh': return 'fa-solid fa-terminal';
            default: return 'fa-solid fa-file-code';
        }
    }

    toggleFile(path, checked) {
        if (checked) {
            this.selectedFilePaths.add(path);
        } else {
            this.selectedFilePaths.delete(path);
        }
        this.schedulePreviewUpdate();
    }

    selectSet(type) {
        if (type === 'all') {
            this.selectedFilePaths = new Set(this.availableFiles.map(f => f.path));
        } else if (type === 'none') {
            this.selectedFilePaths.clear();
        } else if (type === 'notebooks') {
            this.selectedFilePaths = new Set(this.availableFiles.filter(f => f.is_notebook).map(f => f.path));
        } else if (type === 'code') {
            this.selectedFilePaths = new Set(this.availableFiles.filter(f => !f.is_notebook).map(f => f.path));
        }
        this.renderFilesList();
        this.updatePreview();
    }

    setTheme(themeName) {
        this.activeTheme = themeName;
        document.querySelectorAll('.theme-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.theme === themeName);
        });
        this.updatePreview();
    }

    schedulePreviewUpdate() {
        if (this.previewDebounceTimer) clearTimeout(this.previewDebounceTimer);
        this.previewDebounceTimer = setTimeout(() => this.updatePreview(), 300);
    }

    async updatePreview() {
        if (!this.previewFrame) return;

        const filePaths = Array.from(this.selectedFilePaths);
        if (filePaths.length === 0) {
            this.previewFrame.srcdoc = `
                <html style="background:#141417; color:#888; font-family:sans-serif; display:flex; justify-content:center; align-items:center; height:100%;">
                <body><div style="text-align:center;">
                    <i class="fa-solid fa-file-circle-xmark" style="font-size:36px; margin-bottom:12px; opacity:0.5;"></i>
                    <p>No hay archivos seleccionados para vista previa.</p>
                </div></body></html>`;
            return;
        }

        try {
            const res = await fetch('/api/export/pdf-preview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    folder_path: this.currentFolderPath,
                    file_paths: filePaths,
                    theme: this.activeTheme,
                    options: this.options
                })
            });
            const data = prigJson(res);
            if (data.html) {
                this.previewFrame.srcdoc = data.html;
            }
        } catch (e) {
            console.error('Error generando vista previa PDF:', e);
        }
    }

    async downloadPdf() {
        const filePaths = Array.from(this.selectedFilePaths);
        if (filePaths.length === 0) {
            alert('Por favor selecciona al menos un archivo para exportar.');
            return;
        }

        try {
            const res = await fetch('/api/export/pdf-download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    folder_path: this.currentFolderPath,
                    file_paths: filePaths,
                    theme: this.activeTheme,
                    options: this.options
                })
            });

            if (!res.ok) throw new Error('Falló la generación del PDF en servidor');
            
            const blob = await res.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${this.currentFolderName}_codigo_notebooks.pdf`;
            document.body.appendChild(a);
            a.click();
            a.remove();
            window.URL.revokeObjectURL(url);

        } catch (e) {
            alert('Error al descargar PDF: ' + e);
        }
    }

    printPdf() {
        if (!this.previewFrame || !this.previewFrame.contentWindow) {
            alert('Cargando vista previa...');
            return;
        }
        try {
            this.previewFrame.contentWindow.focus();
            this.previewFrame.contentWindow.print();
        } catch (e) {
            alert('Error al abrir la ventana de impresión nativa: ' + e);
        }
    }
}

window.pdfExporterMgr = new PDFExporterManager();
