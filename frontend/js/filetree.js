class FileTreeManager {
    constructor() {
        this.container = document.getElementById('file-tree-container');
        this.searchInput = document.getElementById('tree-search-input');
        this.rawTreeData = [];

        if (this.searchInput) {
            this.searchInput.oninput = () => this.filterTree(this.searchInput.value.toLowerCase());
        }
    }

    async loadTree() {
        try {
            const res = await fetch('/api/tree');
            this.rawTreeData = await res.json();
            this.render(this.rawTreeData, this.container);
        } catch (e) {
            console.error('Error al cargar árbol de archivos:', e);
        }
    }

    filterTree(searchTerm) {
        if (!searchTerm) {
            this.render(this.rawTreeData, this.container);
            return;
        }

        const filterItems = (items) => {
            const result = [];
            items.forEach(item => {
                if (item.is_dir) {
                    const matchingChildren = filterItems(item.children || []);
                    if (matchingChildren.length > 0 || item.name.toLowerCase().includes(searchTerm)) {
                        result.push({ ...item, children: matchingChildren });
                    }
                } else if (item.name.toLowerCase().includes(searchTerm)) {
                    result.push(item);
                }
            });
            return result;
        };

        const filtered = filterItems(this.rawTreeData);
        this.render(filtered, this.container, true);
    }

    render(items, parentEl, expandAll = false) {
        parentEl.innerHTML = '';
        if (!items || items.length === 0) {
            parentEl.innerHTML = '<div style="padding: 10px; color: var(--text-muted);">Sin resultados</div>';
            return;
        }

        items.forEach(item => {
            const el = document.createElement('div');
            el.className = `tree-item ${item.is_dir ? 'dir' : 'file'}`;
            el.dataset.path = item.path || '';
            el.dataset.dir = item.is_dir ? '1' : '';
            const icon = item.is_dir ? 'fa-solid fa-folder' : this.getFileIcon(item.name);
            
            const isNotebook = item.name.endsWith('.ipynb');
            const notebookTag = isNotebook ? '<span style="background:rgba(249,226,175,0.15); color:var(--accent-yellow); font-size:9px; padding:1px 4px; border-radius:3px; margin-left:auto;">NOTEBOOK</span>' : '';
            
            const safePath = (item.path || '').replace(/\\/g, '/').replace(/'/g, "\\'");
            const safeName = (item.name || '').replace(/'/g, "\\'");
            const dirAiBtn = item.is_dir ? '<button title="Análisis inteligente" style="background: var(--accent-blue); color: #111; border: none; border-radius: 4px; padding: 2px 6px; font-size: 10px; font-weight: bold; margin-left: auto; cursor: pointer; display: inline-flex; align-items: center; justify-content: center;" onclick="event.stopPropagation(); window.abrirAprendizajeGuiado();"><i class="fa-solid fa-brain"></i></button>' : '';
            const dirPdfBtn = item.is_dir ? `<button title="Exportar Notebooks y Código a PDF" style="background: #e74c3c; color: #ffffff; border: none; border-radius: 4px; padding: 2px 6px; font-size: 10px; font-weight: bold; margin-left: 4px; cursor: pointer; display: inline-flex; align-items: center; justify-content: center;" onclick="event.stopPropagation(); window.pdfExporterMgr.openModal('${safePath}', '${safeName}');"><i class="fa-solid fa-file-pdf"></i></button>` : '';

            el.innerHTML = `<i class="${icon}"></i> <span class="tree-item-name"></span> ${notebookTag} ${dirAiBtn} ${dirPdfBtn}`;
            // textContent: un nombre de archivo con < o comillas rompía el marcado
            el.querySelector('.tree-item-name').textContent = item.name;

            if (item.is_dir) {
                const childContainer = document.createElement('div');
                childContainer.className = 'tree-children';
                childContainer.style.display = expandAll ? 'block' : 'none';

                el.onclick = (e) => {
                    e.stopPropagation();
                    const isExpanded = childContainer.style.display === 'block';
                    childContainer.style.display = isExpanded ? 'none' : 'block';
                    el.querySelector('i').className = `fa-solid ${isExpanded ? 'fa-folder' : 'fa-folder-open'}`;

                };

                if (item.children && item.children.length > 0) {
                    this.render(item.children, childContainer, expandAll);
                }

                parentEl.appendChild(el);
                parentEl.appendChild(childContainer);
            } else {
                el.onclick = (e) => {
                    e.stopPropagation();
                    this.selectFile(item.path, item.name);
                };
                parentEl.appendChild(el);
            }
        });
    }

    getFileIcon(filename) {
        const ext = filename.split('.').pop().toLowerCase();
        switch (ext) {
            case 'ipynb': return 'fa-solid fa-book-bookmark nb-icon';
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

    async selectFile(path, name) {
        await window.editorMgr.openFileByPath(path, name);
    }

    async openWorkspaceFolder() {
        try {
            // Intentar diálogo nativo del SO primero
            const res = await fetch('/api/workspace/browse', { method: 'POST' });
            // await: sin él `data` era una promesa, data.success nunca existía y el
            // diálogo nativo se ignoraba siempre para pedir la ruta a mano
            const data = await prigJson(res);
            if (data.success) {
                document.getElementById('current-workspace-name').textContent = data.name;
                this.loadTree();
                if (window.terminalMgr) {
                    window.terminalMgr.appendLine(`[Carpeta cargada: ${data.path}]`, 'info');
                }
                return;
            }
        } catch (e) {
            // Fallback manual si el diálogo nativo no responde
        }

        const path = prompt("Ingresa la ruta absoluta de la carpeta a abrir:", "~/");
        if (!path) return;

        try {
            const res = await fetch('/api/workspace/open', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: path })
            });
            const data = await prigJson(res);
            if (data.success) {
                document.getElementById('current-workspace-name').textContent = data.name;
                this.loadTree();
                if (window.terminalMgr) {
                    window.terminalMgr.appendLine(`[Carpeta cargada: ${data.path}]`, 'info');
                }
            } else {
                alert('No se pudo abrir la carpeta: ' + data.error);
            }
        } catch (e) {
            alert('Error abriendo carpeta: ' + e);
        }
    }

    /** `carpeta`: dónde crearlo (menú contextual). Sin ella, junto al archivo activo. */
    async createItem(isDir, carpeta = null) {
        const name = prompt(`Ingresa el nombre del nuevo ${isDir ? 'directorio' : 'archivo'}:`);
        if (!name) return;
        const currentPath = window.editorMgr.getActivePath();
        const baseDir = carpeta !== null ? carpeta
            : (currentPath ? currentPath.substring(0, currentPath.lastIndexOf('/')) : '');
        const targetPath = baseDir ? `${baseDir}/${name}` : name;

        try {
            // prigJson lanza si el backend rechaza: antes se refrescaba el árbol
            // como si se hubiera creado y el elemento simplemente no aparecía.
            const creado = await prigJson(await fetch('/api/create', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: targetPath, is_dir: isDir })
            }));
            this.loadTree();
            // Como en cualquier IDE: el archivo nuevo se abre para escribir en él
            if (!isDir && creado && creado.path) window.editorMgr.openFileByPath(creado.path);
        } catch (e) {
            alert('Error al crear elemento: ' + e);
        }
    }
}

window.fileTreeMgr = new FileTreeManager();
