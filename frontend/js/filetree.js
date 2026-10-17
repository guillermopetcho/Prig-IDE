class FileTreeManager {
    constructor() {
        this.container = document.getElementById('file-tree-container');
        this.searchInput = document.getElementById('tree-search-input');
        this.rawTreeData = [];
        // La segunda carpeta (mitad de abajo): sus archivos se abren en la columna derecha del editor
        this.segunda = null;
        this.rawTreeData2 = [];
        this.currentFolderData = null;
        this.savedProjects = [];
        this.recentProjects = [];

        if (this.searchInput) {
            this.searchInput.oninput = () => this.filterTree(this.searchInput.value.toLowerCase());
        }

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                const modal = document.getElementById('modal-gestor-carpetas');
                if (modal && modal.style.display !== 'none') {
                    modal.style.display = 'none';
                }
            }
        });
    }

    async loadTree() {
        if (!this.container) {
            this.container = document.getElementById('file-tree-container');
        }
        try {
            const res = await fetch('/api/tree');
            this.rawTreeData = await res.json();
            if (this.container) {
                this.render(this.rawTreeData, this.container);
            }
            this.syncWorkspaceIndicator();
        } catch (e) {
            console.error('Error al cargar árbol de archivos:', e);
        }
        await this.cargarSegundaCarpeta();
    }

    /** Lee del backend la segunda carpeta y dibuja su árbol en la mitad de abajo (o la oculta si no hay) */
    async cargarSegundaCarpeta() {
        try {
            const res = await fetch('/api/workspace/segunda');
            if (!res.ok) return;
            this.segunda = (await res.json()).path || null;
            if (this.segunda) {
                const arbol = await fetch(`/api/tree?path=${encodeURIComponent(this.segunda)}`);
                this.rawTreeData2 = arbol.ok ? await arbol.json() : [];
            } else {
                this.rawTreeData2 = [];
            }
        } catch (e) {
            console.error('Error al cargar la segunda carpeta:', e);
        }
        this.mostrarSegundaCarpeta();
    }

    mostrarSegundaCarpeta() {
        const panel = document.getElementById('segunda-carpeta-panel');
        const sidebar = document.getElementById('sidebar-left');
        if (!panel) return;
        panel.classList.toggle('activa', !!this.segunda);
        if (sidebar) sidebar.classList.toggle('dos-carpetas', !!this.segunda);
        const btn = document.getElementById('btn-segunda-carpeta');
        if (btn) {
            btn.style.borderColor = this.segunda ? 'var(--accent-blue)' : '';
            btn.style.background = this.segunda ? 'rgba(137,180,250,0.25)' : '';
            btn.title = this.segunda ? 'Salir de la visión múltiple' : 'Visión múltiple: cargar una segunda carpeta debajo (sus archivos se abren en el editor de la derecha)';
        }
        if (!this.segunda) return;
        const nombre = document.getElementById('segunda-carpeta-nombre');
        if (nombre) {
            nombre.textContent = this.segunda.split('/').filter(Boolean).pop() || this.segunda;
            nombre.title = this.segunda;
        }
        const termino = this.searchInput ? this.searchInput.value.toLowerCase() : '';
        const cont = document.getElementById('file-tree-container-2');
        if (cont) this.render(termino ? this.filtrarItems(this.rawTreeData2, termino) : this.rawTreeData2, cont, !!termino, 1);
    }

    async fijarSegundaCarpeta(ruta) {
        const res = await fetch('/api/workspace/segunda', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: ruta || null })
        });
        if (!res.ok) {
            let detalle = `HTTP ${res.status}`;
            try { detalle = (await res.json()).detail || detalle; } catch (e) {}
            alert(`No se pudo cargar la carpeta: ${detalle}`);
            return;
        }
        await this.cargarSegundaCarpeta();
    }

    /** Elige la segunda carpeta con el diálogo del sistema; si no hay diálogo, pide la ruta */
    async elegirSegundaCarpeta() {
        try {
            const res = await fetch('/api/workspace/segunda/browse', { method: 'POST' });
            if (res.ok) {
                await this.cargarSegundaCarpeta();
                return;
            }
        } catch (e) {}
        const ruta = prompt('Ruta de la segunda carpeta:', this.segunda || '');
        if (ruta && ruta.trim()) await this.fijarSegundaCarpeta(ruta.trim());
    }

    async quitarSegundaCarpeta() {
        await this.fijarSegundaCarpeta(null);
    }

    /** Visión múltiple: con una segunda carpeta la activa (pidiéndola) y sin ella la quita */
    async alternarVisionMultiple() {
        if (this.segunda) {
            await this.quitarSegundaCarpeta();
        } else {
            await this.elegirSegundaCarpeta();
        }
        // Al entrar, el editor ya queda dividido en dos columnas (izquierda la carpeta 1, derecha la 2)
        if (this.segunda && window.editorMgr && window.editorMgr.numColumns < 2) {
            window.editorMgr._abriendoEnColumna = true;
            try { window.editorMgr.setColumnLayout(2); } finally { window.editorMgr._abriendoEnColumna = false; }
        }
    }

    async syncWorkspaceIndicator() {
        try {
            const res = await fetch('/api/workspace/projects');
            if (res.ok) {
                const data = await res.json();
                const actual = data.actual || '';
                const parts = actual.split('/').filter(Boolean);
                const nombre = parts.length > 0 ? parts[parts.length - 1] : actual;

                const elActual = document.getElementById('current-workspace-name');
                if (elActual) elActual.textContent = nombre || 'Sin carpeta';

                const elIndicator = document.getElementById('workspace-folder-indicator-name');
                if (elIndicator) elIndicator.textContent = nombre || 'Sin carpeta';

                const elIndicatorPath = document.getElementById('workspace-folder-indicator');
                if (elIndicatorPath) elIndicatorPath.title = `Ruta: ${actual} (Clic para cambiar)`;

                const elModalBadge = document.getElementById('gestor-carpetas-actual-badge');
                if (elModalBadge) elModalBadge.textContent = actual || 'Ninguna';

                const elBadgeGuardados = document.getElementById('badge-proyectos-guardados');
                if (elBadgeGuardados && Array.isArray(data.guardados)) {
                    elBadgeGuardados.textContent = data.guardados.length;
                }
            }
        } catch (e) {
            // Ignorar errores en sincronización
        }
    }

    filterTree(searchTerm) {
        this.mostrarSegundaCarpeta();
        if (!searchTerm) {
            this.render(this.rawTreeData, this.container);
            return;
        }
        this.render(this.filtrarItems(this.rawTreeData, searchTerm), this.container, true);
    }

    filtrarItems(items, searchTerm) {
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

        return filterItems(items);
    }

    /** col: la columna del editor donde se abren sus archivos (0 la carpeta de trabajo, 1 la segunda) */
    render(items, parentEl, expandAll = false, col = 0) {
        parentEl.innerHTML = '';
        if (!items || items.length === 0) {
            if (parentEl === this.container) {
                parentEl.innerHTML = `
                    <div style="padding: 24px 16px; text-align: center; color: var(--text-muted); font-size: 12px;">
                        <i class="fa-solid fa-folder-open" style="font-size: 28px; margin-bottom: 10px; color: var(--accent-yellow); opacity: 0.7;"></i>
                        <p style="margin: 0 0 12px 0;">Esta carpeta está vacía o no tiene archivos legibles.</p>
                        <button onclick="window.fileTreeMgr && window.fileTreeMgr.openFolderManagerModal('guardados');" style="background: rgba(203,166,247,0.15); border: 1px solid var(--accent-purple); color: var(--accent-purple); padding: 5px 12px; border-radius: 6px; font-size: 11px; cursor: pointer; font-weight: 600;">
                            <i class="fa-solid fa-folder"></i> Cambiar Carpeta
                        </button>
                    </div>
                `;
            } else {
                parentEl.innerHTML = '<div style="padding: 6px 12px; color: var(--text-muted); font-size: 11px;">(vacío)</div>';
            }
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
            const dirAiBtn = item.is_dir ? `<button title="Analizar con IA" class="btn-pensamiento-carpeta" style="background: var(--accent-blue); color: #111; border: none; border-radius: 4px; padding: 2px 6px; font-size: 10px; font-weight: bold; margin-left: auto; cursor: pointer; display: inline-flex; align-items: center; justify-content: center;" onclick="event.stopPropagation(); window.ejecutarPensamientoPersonajeEnArchivo('${safePath}', '${safeName}', this);"><i class="fa-solid fa-brain"></i></button>` : '';
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
                    this.render(item.children, childContainer, expandAll, col);
                }

                parentEl.appendChild(el);
                parentEl.appendChild(childContainer);
            } else {
                el.onclick = (e) => {
                    e.stopPropagation();
                    this.selectFile(item.path, item.name, col);
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

    async selectFile(path, name, col = 0) {
        // Con dos carpetas el editor se divide: la de arriba a la izquierda y la de abajo a la derecha
        if (!window.editorMgr) return;
        const abierto = await window.editorMgr.openFileByPath(path, name, this.segunda ? col : null);
        if (!abierto && window.layoutMgr && window.layoutMgr.mensajeEstado) {
            window.layoutMgr.mensajeEstado(`No se pudo abrir ${name || path}`, 4000);
        }
    }

    escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    openWorkspaceFolder(tab = 'guardados') {
        this.openFolderManagerModal(tab);
    }

    async openFolderManagerModal(tab = 'guardados') {
        const modal = document.getElementById('modal-gestor-carpetas');
        if (!modal) return;
        modal.style.display = 'flex';
        this.switchFolderModalTab(tab);
        await this.cargarProyectos();
        if (tab === 'explorar' && !this.currentFolderData) {
            await this.navegarExplorador();
        }
    }

    switchFolderModalTab(tab) {
        const tabs = ['guardados', 'explorar', 'recientes'];
        tabs.forEach(t => {
            const btn = document.getElementById(`tab-btn-proyectos-${t}`);
            const vista = document.getElementById(`vista-tab-proyectos-${t}`);
            if (t === tab) {
                if (btn) {
                    btn.classList.add('active');
                    btn.style.background = 'var(--accent-purple)';
                    btn.style.color = '#111';
                    btn.style.fontWeight = 'bold';
                }
                if (vista) vista.style.display = 'flex';
            } else {
                if (btn) {
                    btn.classList.remove('active');
                    btn.style.background = 'transparent';
                    btn.style.color = 'var(--text-muted)';
                    btn.style.fontWeight = 'normal';
                }
                if (vista) vista.style.display = 'none';
            }
        });

        if (tab === 'explorar' && !this.currentFolderData) {
            this.navegarExplorador();
        }
    }

    async cargarProyectos() {
        try {
            const res = await fetch('/api/workspace/projects');
            if (!res.ok) return;
            const data = await res.json();
            this.savedProjects = data.guardados || [];
            this.recentProjects = data.recientes || [];

            const badgeActual = document.getElementById('gestor-carpetas-actual-badge');
            if (badgeActual) badgeActual.textContent = data.actual || 'Ninguna';

            const badgeGuardados = document.getElementById('badge-proyectos-guardados');
            if (badgeGuardados) badgeGuardados.textContent = this.savedProjects.length;

            this.renderProyectosGuardados(this.savedProjects);
            this.renderProyectosRecientes(this.recentProjects, data.actual);
        } catch (e) {
            console.error('Error cargando proyectos:', e);
        }
    }

    renderProyectosGuardados(proyectos) {
        const container = document.getElementById('lista-proyectos-guardados');
        if (!container) return;
        container.innerHTML = '';

        if (!proyectos || proyectos.length === 0) {
            container.innerHTML = `
                <div style="padding: 30px; text-align: center; color: var(--text-muted); font-size: 13px;">
                    <i class="fa-solid fa-folder-plus" style="font-size: 32px; color: var(--accent-purple); opacity: 0.6; margin-bottom: 10px;"></i>
                    <p style="margin: 6px 0;">No tienes proyectos guardados aún.</p>
                    <p style="font-size: 11.5px; opacity: 0.8; margin: 0;">Puedes guardar la carpeta activa actual o explorar el disco y guardar tus proyectos favoritos para acceder rápidamente.</p>
                </div>
            `;
            return;
        }

        proyectos.forEach(p => {
            const card = document.createElement('div');
            card.style.cssText = `
                display: flex; justify-content: space-between; align-items: center;
                background: ${p.actual ? 'rgba(166,227,161,0.08)' : 'rgba(255,255,255,0.03)'};
                border: 1px solid ${p.actual ? 'var(--accent-green)' : 'var(--border-color)'};
                border-radius: 8px; padding: 10px 14px; gap: 12px; transition: all 0.2s ease;
            `;

            let badgesHtml = '';
            if (p.actual) {
                badgesHtml += `<span style="background: rgba(166,227,161,0.2); color: var(--accent-green); font-size: 9.5px; padding: 2px 6px; border-radius: 4px; font-weight: bold;"><i class="fa-solid fa-check"></i> ACTIVO</span>`;
            }
            if (!p.exists) {
                badgesHtml += `<span style="background: rgba(243,139,168,0.2); color: var(--accent-red); font-size: 9.5px; padding: 2px 6px; border-radius: 4px;"><i class="fa-solid fa-triangle-exclamation"></i> NO ENCONTRADA</span>`;
            }
            if (p.source === 'biblioteca') {
                badgesHtml += `<span style="background: rgba(203,166,247,0.18); color: var(--accent-purple); font-size: 9.5px; padding: 2px 6px; border-radius: 4px;"><i class="fa-solid fa-book"></i> BIBLIOTECA</span>`;
            }

            const safePath = p.path.replace(/"/g, '&quot;');
            card.innerHTML = `
                <div style="display: flex; align-items: center; gap: 12px; min-width: 0; flex: 1;">
                    <i class="fa-solid ${p.actual ? 'fa-folder-open' : 'fa-folder-tree'}" style="color: ${p.actual ? 'var(--accent-green)' : 'var(--accent-yellow)'}; font-size: 1.4rem;"></i>
                    <div style="min-width: 0; flex: 1;">
                        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 2px;">
                            <span style="font-weight: 600; font-size: 13px; color: #fff; text-overflow: ellipsis; white-space: nowrap; overflow: hidden;">${this.escapeHtml(p.name)}</span>
                            ${badgesHtml}
                        </div>
                        <div style="font-family: monospace; font-size: 11px; color: var(--text-muted); text-overflow: ellipsis; white-space: nowrap; overflow: hidden;" title="${safePath}">${this.escapeHtml(p.path)}</div>
                    </div>
                </div>
                <div style="display: flex; gap: 6px; flex-shrink: 0;">
                    ${!p.actual ? `
                    <button class="ubuntu-btn" style="background: var(--accent-blue); color: #111; border: none; padding: 5px 12px; border-radius: 5px; font-size: 11.5px; font-weight: bold; cursor: pointer;" onclick="window.fileTreeMgr.abrirRutaProyecto('${safePath}')">
                        <i class="fa-solid fa-arrow-right-to-bracket"></i> Abrir
                    </button>` : `
                    <span style="color: var(--accent-green); font-size: 11.5px; font-weight: bold; padding: 5px 10px;"><i class="fa-solid fa-circle-dot"></i> Abierto</span>`}
                    <button class="ubuntu-btn" style="background: rgba(243,139,168,0.15); border: 1px solid rgba(243,139,168,0.3); color: var(--accent-red); padding: 5px 8px; border-radius: 5px; font-size: 11px; cursor: pointer;" title="Quitar de rutas guardadas" onclick="window.fileTreeMgr.eliminarProyectoGuardado('${safePath}')">
                        <i class="fa-solid fa-trash-can"></i>
                    </button>
                </div>
            `;
            container.appendChild(card);
        });
    }

    renderProyectosRecientes(recientes, actual) {
        const container = document.getElementById('lista-proyectos-recientes');
        if (!container) return;
        container.innerHTML = '';

        if (!recientes || recientes.length === 0) {
            container.innerHTML = `<div style="padding: 20px; color: var(--text-muted); font-size: 12px; text-align: center;">No hay carpetas recientes en el historial.</div>`;
            return;
        }

        recientes.forEach(ruta => {
            const isActual = ruta === actual;
            const card = document.createElement('div');
            card.style.cssText = `
                display: flex; justify-content: space-between; align-items: center;
                background: rgba(255,255,255,0.02); border: 1px solid var(--border-color);
                border-radius: 6px; padding: 8px 12px; gap: 10px;
            `;

            const parts = ruta.split('/').filter(Boolean);
            const nombre = parts.length > 0 ? parts[parts.length - 1] : ruta;
            const safePath = ruta.replace(/"/g, '&quot;');

            card.innerHTML = `
                <div style="display: flex; align-items: center; gap: 10px; min-width: 0; flex: 1;">
                    <i class="fa-solid fa-clock-rotate-left" style="color: var(--accent-blue); font-size: 1.1rem;"></i>
                    <div style="min-width: 0; flex: 1;">
                        <div style="font-weight: 600; font-size: 12px; color: #fff;">${this.escapeHtml(nombre)} ${isActual ? '<span style="color: var(--accent-green); font-size: 10px;">(ACTIVO)</span>' : ''}</div>
                        <div style="font-family: monospace; font-size: 10.5px; color: var(--text-muted); text-overflow: ellipsis; white-space: nowrap; overflow: hidden;" title="${safePath}">${this.escapeHtml(ruta)}</div>
                    </div>
                </div>
                <div style="display: flex; gap: 6px; flex-shrink: 0;">
                    ${!isActual ? `
                    <button class="ubuntu-btn" style="background: rgba(137,180,250,0.15); border: 1px solid var(--accent-blue); color: var(--accent-blue); padding: 4px 10px; border-radius: 4px; font-size: 11px; cursor: pointer;" onclick="window.fileTreeMgr.abrirRutaProyecto('${safePath}')">
                        <i class="fa-solid fa-folder-open"></i> Abrir
                    </button>` : ''}
                    <button class="ubuntu-btn" style="background: rgba(203,166,247,0.15); border: 1px solid var(--accent-purple); color: var(--accent-purple); padding: 4px 8px; border-radius: 4px; font-size: 11px; cursor: pointer;" title="Guardar en proyectos permanentemente" onclick="window.fileTreeMgr.guardarRutaComoProyecto('${safePath}', '${this.escapeHtml(nombre)}')">
                        <i class="fa-solid fa-star"></i> Guardar
                    </button>
                </div>
            `;
            container.appendChild(card);
        });
    }

    filtrarProyectosGuardados(texto) {
        const q = (texto || '').toLowerCase().trim();
        if (!q) {
            this.renderProyectosGuardados(this.savedProjects);
            return;
        }
        const filtrados = this.savedProjects.filter(p =>
            (p.name || '').toLowerCase().includes(q) || (p.path || '').toLowerCase().includes(q)
        );
        this.renderProyectosGuardados(filtrados);
    }

    async navegarExplorador(ruta = '') {
        const grid = document.getElementById('explorador-subcarpetas-grid');
        if (grid) {
            grid.innerHTML = '<div style="padding: 20px; color: var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i> Explorando carpetas...</div>';
        }

        try {
            const url = ruta ? `/api/workspace/directories?ruta=${encodeURIComponent(ruta)}` : '/api/workspace/directories';
            const res = await fetch(url);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            this.currentFolderData = data;

            const inputRuta = document.getElementById('input-ruta-seleccionada');
            if (inputRuta) inputRuta.value = data.current;

            const btnSubir = document.getElementById('btn-explorar-subir');
            if (btnSubir) {
                btnSubir.disabled = !data.parent;
                btnSubir.style.opacity = data.parent ? '1' : '0.4';
                btnSubir.style.cursor = data.parent ? 'pointer' : 'not-allowed';
            }

            this.renderAtajos(data.shortcuts || []);
            this.renderMigas(data.current);
            this.renderSubcarpetasGrid(data.subdirectories || []);

            const filtroInput = document.getElementById('filtro-subcarpetas');
            if (filtroInput) filtroInput.value = '';
        } catch (e) {
            if (grid) grid.innerHTML = `<div style="padding: 20px; color: var(--accent-red);">Error al explorar ruta: ${e.message}</div>`;
        }
    }

    renderAtajos(atajos) {
        const container = document.getElementById('explorador-atajos-lista');
        if (!container) return;
        container.innerHTML = '';

        atajos.forEach(a => {
            const btn = document.createElement('button');
            btn.className = 'ubuntu-btn';
            btn.style.cssText = `
                display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-radius: 5px;
                background: transparent; border: none; color: var(--text-main); font-size: 11.5px;
                text-align: left; width: 100%; cursor: pointer; transition: background 0.15s ease;
            `;
            btn.onmouseover = () => { btn.style.background = 'rgba(255,255,255,0.08)'; };
            btn.onmouseout = () => { btn.style.background = 'transparent'; };
            btn.onclick = () => this.navegarExplorador(a.path);
            btn.innerHTML = `<i class="fa-solid ${a.icon || 'fa-folder'}" style="color: var(--accent-yellow); font-size: 12px; width: 14px;"></i> <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${this.escapeHtml(a.name)}</span>`;
            btn.title = a.path;
            container.appendChild(btn);
        });
    }

    renderMigas(rutaActual) {
        const container = document.getElementById('explorador-migas');
        if (!container) return;
        container.innerHTML = '';

        const partes = (rutaActual || '').split('/').filter(Boolean);

        // Botón raíz
        const btnRaiz = document.createElement('span');
        btnRaiz.style.cssText = 'cursor: pointer; padding: 2px 4px; border-radius: 3px;';
        btnRaiz.innerHTML = '<i class="fa-solid fa-hard-drive"></i> /';
        btnRaiz.onclick = () => this.navegarExplorador('/');
        container.appendChild(btnRaiz);

        let acumulado = '';
        partes.forEach((p, idx) => {
            acumulado += '/' + p;
            const separador = document.createElement('span');
            separador.style.color = 'var(--text-muted)';
            separador.textContent = '>';
            container.appendChild(separador);

            const item = document.createElement('span');
            const target = acumulado;
            const esUltimo = idx === partes.length - 1;
            item.style.cssText = `cursor: pointer; padding: 2px 4px; border-radius: 3px; ${esUltimo ? 'font-weight: bold; color: #fff;' : 'color: var(--accent-blue);'}`;
            item.textContent = p;
            item.onclick = () => this.navegarExplorador(target);
            container.appendChild(item);
        });
    }

    renderSubcarpetasGrid(subdirectorios) {
        const grid = document.getElementById('explorador-subcarpetas-grid');
        if (!grid) return;
        grid.innerHTML = '';

        if (!subdirectorios || subdirectorios.length === 0) {
            grid.innerHTML = `<div style="grid-column: 1 / -1; padding: 30px; text-align: center; color: var(--text-muted); font-size: 12px;">(No hay subcarpetas visibles en este directorio)</div>`;
            return;
        }

        subdirectorios.forEach(sub => {
            const card = document.createElement('div');
            card.style.cssText = `
                display: flex; align-items: center; gap: 8px; padding: 7px 10px; border-radius: 6px;
                background: rgba(255,255,255,0.04); border: 1px solid var(--border-color);
                cursor: pointer; overflow: hidden; user-select: none; transition: all 0.15s ease;
            `;
            card.onmouseover = () => { card.style.background = 'rgba(137,180,250,0.12)'; card.style.borderColor = 'var(--accent-blue)'; };
            card.onmouseout = () => { card.style.background = 'rgba(255,255,255,0.04)'; card.style.borderColor = 'var(--border-color)'; };

            card.innerHTML = `
                <i class="fa-solid fa-folder" style="color: var(--accent-yellow); font-size: 1.1rem; flex-shrink: 0;"></i>
                <span style="font-size: 12px; color: #fff; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${this.escapeHtml(sub.name)}</span>
            `;

            card.onclick = () => {
                const inputRuta = document.getElementById('input-ruta-seleccionada');
                if (inputRuta) inputRuta.value = sub.path;
            };

            card.ondblclick = () => {
                this.navegarExplorador(sub.path);
            };

            grid.appendChild(card);
        });
    }

    filtrarSubcarpetas(texto) {
        if (!this.currentFolderData || !this.currentFolderData.subdirectories) return;
        const q = (texto || '').toLowerCase().trim();
        if (!q) {
            this.renderSubcarpetasGrid(this.currentFolderData.subdirectories);
            return;
        }
        const filtradas = this.currentFolderData.subdirectories.filter(s =>
            (s.name || '').toLowerCase().includes(q)
        );
        this.renderSubcarpetasGrid(filtradas);
    }

    explorarSubirNivel() {
        if (this.currentFolderData && this.currentFolderData.parent) {
            this.navegarExplorador(this.currentFolderData.parent);
        }
    }

    async abrirCarpetaExplorada(guardarTambien = false) {
        const inputRuta = document.getElementById('input-ruta-seleccionada');
        const ruta = (inputRuta ? inputRuta.value : '').trim() || (this.currentFolderData ? this.currentFolderData.current : '');
        if (!ruta) return;

        if (guardarTambien) {
            const parts = ruta.split('/').filter(Boolean);
            const nombre = parts.length > 0 ? parts[parts.length - 1] : ruta;
            await this.guardarRutaComoProyecto(ruta, nombre, false);
        }

        await this.abrirRutaProyecto(ruta);
    }

    async abrirRutaProyecto(ruta) {
        if (!ruta) return;
        try {
            const res = await fetch('/api/workspace/open', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: ruta })
            });
            const data = await prigJson(res);
            if (data.success) {
                const modal = document.getElementById('modal-gestor-carpetas');
                if (modal) modal.style.display = 'none';

                await this.loadTree();
                await this.syncWorkspaceIndicator();

                if (window.terminalMgr) {
                    window.terminalMgr.appendLine(`[Espacio de trabajo abierto: ${data.path}]`, 'info');
                }
            } else {
                alert('No se pudo abrir la carpeta: ' + (data.error || 'Error desconocido'));
            }
        } catch (e) {
            alert('Error abriendo espacio de trabajo: ' + e.message);
        }
    }

    async guardarCarpetaActualEnBiblioteca() {
        try {
            const res = await fetch('/api/workspace/projects');
            const data = await res.json();
            const actual = data.actual;
            if (!actual) {
                alert('No hay ninguna carpeta de espacio de trabajo activa actualmente.');
                return;
            }

            const parts = actual.split('/').filter(Boolean);
            const nombreSugerido = parts.length > 0 ? parts[parts.length - 1] : 'Proyecto';
            const nombre = prompt('Nombre para identificar este proyecto en la Biblioteca:', nombreSugerido);
            if (!nombre) return;

            await this.guardarRutaComoProyecto(actual, nombre, true);
        } catch (e) {
            alert('Error al guardar carpeta actual: ' + e.message);
        }
    }

    async promptAnadirProyecto() {
        const ruta = prompt('Ingresa la ruta absoluta de la carpeta del proyecto a vincular:', '~/');
        if (!ruta) return;

        const parts = ruta.trim().split('/').filter(Boolean);
        const nombreSugerido = parts.length > 0 ? parts[parts.length - 1] : 'Mi Proyecto';
        const nombre = prompt('Nombre descriptivo para el proyecto:', nombreSugerido);
        if (!nombre) return;

        await this.guardarRutaComoProyecto(ruta.trim(), nombre.trim(), true);
    }

    async guardarRutaComoProyecto(ruta, nombre, recargar = true) {
        try {
            const res = await fetch('/api/workspace/projects/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: ruta, nombre: nombre, origen: 'biblioteca' })
            });
            const data = await res.json();
            if (res.ok && data.success) {
                if (recargar) {
                    await this.cargarProyectos();
                    if (window.bookLibraryMgr && window.bookLibraryMgr.allBooks) {
                        window.bookLibraryMgr.loadBooks();
                    }
                }
                return true;
            } else {
                alert('No se pudo guardar el proyecto: ' + (data.detail || data.error || 'Error desconocido'));
            }
        } catch (e) {
            alert('Error al guardar proyecto: ' + e.message);
        }
        return false;
    }

    async eliminarProyectoGuardado(ruta) {
        if (!confirm(`¿Desvincular este proyecto de tus rutas guardadas?\n\n${ruta}\n\nNota: Los archivos físicos NO se borrarán.`)) {
            return;
        }

        try {
            const res = await fetch('/api/workspace/projects/remove', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: ruta })
            });
            const data = await res.json();
            if (res.ok && data.success) {
                await this.cargarProyectos();
                if (window.bookLibraryMgr && window.bookLibraryMgr.allBooks) {
                    window.bookLibraryMgr.loadBooks();
                }
            } else {
                alert('No se pudo desvincular: ' + (data.detail || data.error));
            }
        } catch (e) {
            alert('Error al desvincular proyecto: ' + e.message);
        }
    }

    async limpiarRecientes() {
        if (!confirm('¿Deseas limpiar el historial de carpetas recientes?')) return;
        try {
            await fetch('/api/ide/recientes', { method: 'DELETE' });
            await this.cargarProyectos();
        } catch (e) {
            alert('Error al limpiar recientes: ' + e.message);
        }
    }

    async abrirDialogoNativo() {
        try {
            const res = await fetch('/api/workspace/browse', { method: 'POST' });
            const data = await prigJson(res);
            if (data.success) {
                const modal = document.getElementById('modal-gestor-carpetas');
                if (modal) modal.style.display = 'none';

                await this.loadTree();
                await this.syncWorkspaceIndicator();

                if (window.terminalMgr) {
                    window.terminalMgr.appendLine(`[Carpeta cargada: ${data.path}]`, 'info');
                }
                return true;
            }
        } catch (e) {
            console.warn('Diálogo nativo no disponible o cancelado:', e);
        }
        return false;
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

/**
 * Analiza con IA y ejecuta todo el razonamiento del personaje del proyecto sobre una carpeta o workspace,
 * escribiéndolo en un archivo PENSAMIENTO_DEL_PROYECTO.md y abriéndolo directamente en vista Markdown.
 */
window.ejecutarPensamientoPersonajeEnArchivo = async function(carpetaPath, carpetaNombre, btnEl = null) {
    const nombre = carpetaNombre || 'Proyecto';
    const notifMsg = `🧠 Analizando con IA "${nombre}"...`;
    
    if (window.layoutMgr && typeof window.layoutMgr.mensajeEstado === 'function') {
        window.layoutMgr.mensajeEstado(notifMsg, 6000);
    }

    const btn = btnEl || (window.event && window.event.target ? window.event.target.closest('button') : null);
    let oldHtml = null;
    if (btn) {
        oldHtml = btn.innerHTML;
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
        btn.disabled = true;
    }

    try {
        const temaId = (window.DIRECTOR_ASCII && window.DIRECTOR_ASCII.temaActivo) || 'tema_mecha_patrol';
        const resp = await fetch('/api/llm/ejecutar_pensamiento_proyecto', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                carpeta: carpetaPath || '',
                tema_id: temaId
            })
        });

        if (!resp.ok) {
            const errTxt = await resp.text();
            throw new Error(`Error en servidor (${resp.status}): ${errTxt}`);
        }

        const data = await resp.json();
        if (!data.ok) {
            throw new Error(data.error || 'No se pudo generar el archivo de pensamiento.');
        }

        // Recargar el árbol para mostrar PENSAMIENTO_DEL_PROYECTO.md
        if (window.fileTreeMgr && typeof window.fileTreeMgr.loadTree === 'function') {
            await window.fileTreeMgr.loadTree();
        }

        // Abrir el archivo directamente en el editor en modo Markdown
        if (data.archivo && window.editorMgr && typeof window.editorMgr.openFileByPath === 'function') {
            await window.editorMgr.openFileByPath(data.archivo, data.nombre || 'PENSAMIENTO_DEL_PROYECTO.md');
            if (typeof window.editorMgr.showMarkdownView === 'function') {
                window.editorMgr.showMarkdownView();
            }
        }

        const exitoMsg = `✅ Análisis con IA completado en ${data.nombre || 'PENSAMIENTO_DEL_PROYECTO.md'}`;
        if (window.layoutMgr && typeof window.layoutMgr.mensajeEstado === 'function') {
            window.layoutMgr.mensajeEstado(exitoMsg, 4500);
        } else {
            console.log(exitoMsg);
        }
    } catch (err) {
        console.error('Error al analizar con IA en archivo:', err);
        const errDesc = `Error: ${err.message || 'No se pudo completar el análisis'}`;
        if (window.layoutMgr && typeof window.layoutMgr.mensajeEstado === 'function') {
            window.layoutMgr.mensajeEstado(errDesc, 4000);
        } else {
            alert(errDesc);
        }
    } finally {
        if (btn && oldHtml) {
            btn.innerHTML = oldHtml;
            btn.disabled = false;
        }
    }
};
