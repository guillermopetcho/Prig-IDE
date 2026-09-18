class BookLibraryManager {
    constructor() {
        this.modal = document.getElementById('modal-book-library');
        this.booksListContainer = document.getElementById('book-list-items');
        this.metadataPane = document.getElementById('pane-book-metadata');
        this.readerPane = document.getElementById('pane-book-reader');
        this.viewerContainer = document.getElementById('book-viewer-content');
        this.snippetsContainer = document.getElementById('book-snippets-list');
        this.searchInput = document.getElementById('input-search-books');
        this.statusEl = document.getElementById('book-header-status');

        // Barra de estado del índice de conocimiento
        this.indexSummaryEl = document.getElementById('library-index-summary');
        this.indexProgressEl = document.getElementById('library-index-progress');
        this.indexFillEl = document.getElementById('library-index-bar-fill');
        this.indexDetailEl = document.getElementById('library-index-detail');
        this.btnIndex = document.getElementById('btn-index-library');
        this.indexPollTimer = null;

        this.currentBook = null;      // uid: ruta relativa dentro de la biblioteca
        this.currentBookData = null;
        this.activeTab = 'metadata';
        this.allBooks = [];

        this.activeCategory = 'ALL';
        this.initEvents();
    }

    initEvents() {
        const btnClose = document.getElementById('btn-close-book-library');
        if (btnClose) btnClose.onclick = () => this.closeModal();

        const btnRefresh = document.getElementById('btn-refresh-books');
        if (btnRefresh) btnRefresh.onclick = () => this.loadBooks();

        const btnCreateCite = document.getElementById('btn-create-book-snippet');
        if (btnCreateCite) btnCreateCite.onclick = () => this.createSnippetFromSelection();

        const btnAnalyze = document.getElementById('btn-analyze-book-ai');
        if (btnAnalyze) btnAnalyze.onclick = () => this.analyzeCurrentDocument();

        const btnImport = document.getElementById('btn-import-book-file');
        if (btnImport) btnImport.onclick = () => this.importDocumentFile();

        const btnDelete = document.getElementById('btn-delete-book');
        if (btnDelete) btnDelete.onclick = () => this.deleteCurrentBook();

        if (this.btnIndex) this.btnIndex.onclick = () => this.startIndexing();

        if (this.searchInput) {
            this.searchInput.oninput = () => this.filterBooksList(this.searchInput.value.trim().toLowerCase());
        }

        // Listener para selector de categorías Knowledge Repository
        const catContainer = document.getElementById('library-category-pills');
        if (catContainer) {
            catContainer.onclick = (e) => {
                const btn = e.target.closest('.cat-pill');
                if (btn) {
                    const cat = btn.getAttribute('data-cat');
                    this.selectCategoryFilter(cat, btn);
                }
            };
        }

        // El acceso vive en Herramientas › Biblioteca (Ctrl+1).

        // Tecla Escape para cerrar
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.modal && this.modal.style.display === 'flex') {
                this.closeModal();
            }
        });
    }

    selectCategoryFilter(cat, clickedBtn) {
        this.activeCategory = cat;
        const pills = document.querySelectorAll('.cat-pill');
        pills.forEach(p => {
            p.classList.remove('active');
            p.style.background = 'var(--bg-dark)';
            p.style.color = 'var(--text-muted)';
            p.style.border = '1px solid var(--border-color)';
            p.style.fontWeight = 'normal';
        });

        if (clickedBtn) {
            clickedBtn.classList.add('active');
            clickedBtn.style.background = 'var(--accent-purple)';
            clickedBtn.style.color = '#111';
            clickedBtn.style.fontWeight = 'bold';
            clickedBtn.style.border = 'none';
        }

        this.filterBooksList(this.searchInput ? this.searchInput.value.trim().toLowerCase() : '');
    }

    async openModal() {
        this.modal = this.modal || document.getElementById('modal-book-library');
        if (!this.modal) return;
        this.modal.style.display = 'flex';
        await this.loadBooks();
        await this.loadSavedSnippets();
        this.refreshIndexStatus();
    }

    closeModal() {
        if (this.modal) this.modal.style.display = 'none';
        this.stopIndexPolling();
    }

    // ==========================================
    // ÍNDICE DE CONOCIMIENTO
    // ==========================================

    stopIndexPolling() {
        if (this.indexPollTimer) {
            clearInterval(this.indexPollTimer);
            this.indexPollTimer = null;
        }
    }

    /** Lee el estado del índice y lo pinta en la barra lateral */
    async refreshIndexStatus() {
        if (!this.indexSummaryEl) return;
        try {
            const res = await fetch('/api/knowledge/status');
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const st = await res.json();
            this.renderIndexStatus(st);
            return st;
        } catch (e) {
            this.indexSummaryEl.innerHTML =
                `<span style="color: var(--accent-red);"><i class="fa-solid fa-triangle-exclamation"></i> Índice no disponible</span>`;
            return null;
        }
    }

    renderIndexStatus(st) {
        const job = st.job || {};
        const indexados = (st.counts && st.counts.books) || 0;
        const fragmentos = (st.counts && st.counts.chunks) || 0;
        const pendientes = st.files_pending || 0;

        if (job.running) {
            const pct = job.total > 0 ? Math.round((job.processed / job.total) * 100) : 0;
            this.indexSummaryEl.innerHTML =
                `<span style="color: var(--accent-blue);"><i class="fa-solid fa-spinner fa-spin"></i> Indexando ${job.processed}/${job.total}</span>`;
            if (this.indexProgressEl) this.indexProgressEl.style.display = 'block';
            if (this.indexFillEl) this.indexFillEl.style.width = `${pct}%`;
            if (this.indexDetailEl) this.indexDetailEl.textContent = job.current_file || '';
            if (this.btnIndex) { this.btnIndex.disabled = true; this.btnIndex.style.opacity = '0.5'; }
            return;
        }

        if (this.indexProgressEl) this.indexProgressEl.style.display = 'none';
        if (this.btnIndex) {
            this.btnIndex.disabled = false;
            this.btnIndex.style.opacity = '1';
            this.btnIndex.innerHTML = pendientes > 0
                ? `<i class="fa-solid fa-layer-group"></i> Indexar ${pendientes}`
                : `<i class="fa-solid fa-rotate"></i> Reindexar`;
        }

        // Los errores de la última pasada no deben quedar ocultos
        const fallos = (job.errors || []).length;
        const avisoFallos = fallos > 0
            ? ` · <span style="color: var(--accent-red);" title="${(job.errors || []).join(' | ').replace(/"/g, "'")}">${fallos} con error</span>`
            : '';

        if (pendientes > 0) {
            this.indexSummaryEl.innerHTML =
                `<span style="color: var(--accent-yellow);"><i class="fa-solid fa-clock"></i> ${pendientes} sin indexar</span>` +
                `<span style="color: var(--text-muted);"> · ${indexados} listos</span>${avisoFallos}`;
        } else if (indexados > 0) {
            this.indexSummaryEl.innerHTML =
                `<span style="color: var(--accent-green);"><i class="fa-solid fa-circle-check"></i> ${indexados} indexados</span>` +
                `<span style="color: var(--text-muted);"> · ${fragmentos} fragmentos</span>${avisoFallos}`;
        } else {
            this.indexSummaryEl.innerHTML =
                `<span style="color: var(--text-muted);">Biblioteca sin indexar — el tutor todavía no puede citarla</span>`;
        }
    }

    async startIndexing() {
        if (!this.btnIndex) return;
        this.btnIndex.disabled = true;
        this.btnIndex.style.opacity = '0.5';

        try {
            const res = await fetch('/api/knowledge/index', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ force: false })
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
        } catch (e) {
            this.indexSummaryEl.innerHTML =
                `<span style="color: var(--accent-red);"><i class="fa-solid fa-triangle-exclamation"></i> No se pudo iniciar: ${e.message}</span>`;
            this.btnIndex.disabled = false;
            this.btnIndex.style.opacity = '1';
            return;
        }

        // Sondear hasta que termine; al acabar, refrescar la lista para que se vean
        // las insignias de "Indexado".
        this.stopIndexPolling();
        this.indexPollTimer = setInterval(async () => {
            const st = await this.refreshIndexStatus();
            if (st && st.job && !st.job.running) {
                this.stopIndexPolling();
                await this.loadBooks();
            }
        }, 700);
    }

    // ==========================================
    // ELIMINAR
    // ==========================================

    async deleteCurrentBook() {
        if (!this.currentBook) {
            alert('Selecciona primero un elemento de la biblioteca.');
            return;
        }

        const bookObj = this.allBooks.find(b => this.bookKey(b) === this.currentBook);
        const nombre = (bookObj && (bookObj.title || bookObj.filename)) || this.currentBook;

        if (!confirm(`¿Eliminar "${nombre}" de la biblioteca?\n\nSe borrará el archivo, su ficha de IA y su entrada del índice. Esta acción no se puede deshacer.`)) {
            return;
        }

        try {
            const res = await fetch('/api/books/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: this.currentBook })
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);

            this.currentBook = null;
            this.currentBookData = null;
            if (this.metadataPane) this.metadataPane.innerHTML = '';
            if (this.viewerContainer) this.viewerContainer.innerHTML = '';

            await this.loadBooks();
            this.refreshIndexStatus();
        } catch (e) {
            alert(`No se pudo eliminar: ${e.message}`);
        }
    }

    switchTab(tabName) {
        this.activeTab = tabName;
        const btnMeta = document.getElementById('tab-btn-book-metadata');
        const btnReader = document.getElementById('tab-btn-book-reader');

        if (tabName === 'metadata') {
            if (btnMeta) btnMeta.classList.add('active');
            if (btnReader) btnReader.classList.remove('active');
            if (this.metadataPane) this.metadataPane.style.display = 'block';
            if (this.readerPane) this.readerPane.style.display = 'none';
        } else {
            if (btnReader) btnReader.classList.add('active');
            if (btnMeta) btnMeta.classList.remove('active');
            if (this.metadataPane) this.metadataPane.style.display = 'none';
            if (this.readerPane) this.readerPane.style.display = 'block';
        }
    }

    async loadBooks() {
        if (!this.booksListContainer) return;
        this.booksListContainer.innerHTML = '<div style="padding:15px; color:var(--text-muted); text-align:center;"><i class="fa-solid fa-spinner fa-spin"></i> Cargando biblioteca...</div>';

        try {
            const res = await fetch('/api/books/list');
            const books = await res.json();
            this.allBooks = books || [];

            this.filterBooksList(this.searchInput ? this.searchInput.value.trim().toLowerCase() : '');

            // Abrir el primer documento si no hay ninguno abierto
            if (this.allBooks.length > 0 && !this.currentBook) {
                this.openBook(this.bookKey(this.allBooks[0]));
            }
        } catch (e) {
            console.error("Error cargando biblioteca:", e);
            this.booksListContainer.innerHTML = `<div style="padding:15px; color:var(--accent-red);">Error al cargar biblioteca: ${e.message}</div>`;
        }
    }

    /**
     * Identidad de un elemento. `uid` es la ruta relativa ("books/notas.md") y
     * distingue archivos con el mismo nombre en categorías distintas; `id` (solo el
     * nombre) queda como reserva para respuestas antiguas.
     */
    bookKey(b) {
        return b.uid || b.id;
    }

    /** Título legible del elemento abierto (el uid es una ruta, no sirve para mostrar) */
    currentBookTitle() {
        const b = this.allBooks.find(x => this.bookKey(x) === this.currentBook);
        return (b && (b.title || b.filename)) || this.currentBook || '';
    }

    filterBooksList(query) {
        let filtered = this.allBooks;

        // Filtrar por categoría
        if (this.activeCategory && this.activeCategory !== 'ALL') {
            filtered = filtered.filter(b => (b.category || b.category_id || '').toLowerCase() === this.activeCategory.toLowerCase());
        }

        // Filtrar por texto de búsqueda
        if (query) {
            filtered = filtered.filter(b => {
                // String(): si el backend devolvía title nulo (ficha de IA sin ese
                // campo), b.title.toLowerCase() lanzaba TypeError y la búsqueda
                // dejaba la biblioteca entera en blanco.
                const title = String(b.title || '').toLowerCase();
                const filename = String(b.filename || '').toLowerCase();
                const titleMatch = title.includes(query) || filename.includes(query);
                let metaMatch = false;
                if (b.metadata) {
                    const topics = (b.metadata.topics || []).join(' ').toLowerCase();
                    const concepts = (b.metadata.concepts || []).join(' ').toLowerCase();
                    const libs = (b.metadata.libraries || []).join(' ').toLowerCase();
                    metaMatch = topics.includes(query) || concepts.includes(query) || libs.includes(query) || (b.metadata.level || '').toLowerCase().includes(query);
                }
                return titleMatch || metaMatch;
            });
        }

        this.renderBooksList(filtered);
    }

    renderBooksList(books) {
        if (!this.booksListContainer) return;
        if (!books || books.length === 0) {
            this.booksListContainer.innerHTML = '<div style="padding:15px; color:var(--text-muted); font-size:12px; text-align:center;">No se encontraron elementos en esta categoría. Importa archivos a <code>~/.prig_books</code>.</div>';
            return;
        }

        this.booksListContainer.innerHTML = '';
        books.forEach(b => {
            const key = this.bookKey(b);
            const isSelected = this.currentBook === key;
            const item = document.createElement('div');
            item.className = `book-item-card ${isSelected ? 'active' : ''}`;
            item.style.cssText = `padding: 8px 10px; border-radius: 6px; cursor: pointer; background: ${isSelected ? 'rgba(137, 180, 250, 0.15)' : 'var(--bg-dark)'}; border: 1px solid ${isSelected ? 'var(--accent-blue)' : 'var(--border-color)'}; transition: all 0.2s ease;`;

            let iconClass = 'fa-file-lines';
            let iconColor = 'var(--accent-blue)';
            const cat = (b.category || b.category_id || 'BOOKS').toUpperCase();

            if (cat === 'BOOKS' || b.ext === 'pdf') { iconClass = 'fa-book'; iconColor = 'var(--accent-purple)'; }
            else if (cat === 'DOCUMENTATION') { iconClass = 'fa-file-lines'; iconColor = 'var(--accent-blue)'; }
            else if (cat === 'PAPERS') { iconClass = 'fa-newspaper'; iconColor = 'var(--accent-yellow)'; }
            else if (cat === 'CODE' || b.ext === 'py') { iconClass = 'fa-code'; iconColor = 'var(--accent-green)'; }
            else if (cat === 'NOTEBOOKS' || b.ext === 'ipynb') { iconClass = 'fa-book-bookmark'; iconColor = 'var(--accent-yellow)'; }
            else if (cat === 'DATASETS') { iconClass = 'fa-database'; iconColor = 'var(--accent-red)'; }
            else if (cat === 'PROJECTS') { iconClass = 'fa-folder-tree'; iconColor = 'var(--accent-purple)'; }

            let badgesHtml = '';
            if (b.analysis_failed) {
                // Un análisis fallido lucía igual que uno correcto: la ficha inventada
                // se marcaba como "analizado" y el usuario no sabía que era falsa.
                badgesHtml += `<span style="font-size:9px; background: rgba(243,139,168,0.15); color: var(--accent-red); padding: 1px 4px; border-radius: 3px;" title="El análisis con IA falló"><i class="fa-solid fa-triangle-exclamation"></i> Falló</span>`;
            } else if (b.analyzed && b.metadata) {
                badgesHtml += `<span style="font-size:9px; background: rgba(249,226,175,0.15); color: var(--accent-yellow); padding: 1px 4px; border-radius: 3px;" title="Metadatos IA Listos"><i class="fa-solid fa-sparkles"></i> IA</span>`;
            }
            if (b.indexed) {
                badgesHtml += `<span style="font-size:9px; background: rgba(166,227,161,0.15); color: var(--accent-green); padding: 1px 4px; border-radius: 3px; margin-left:4px;" title="Indexado: el tutor puede consultarlo y citarlo"><i class="fa-solid fa-magnifying-glass"></i> Indexado</span>`;
            } else if (b.indexable) {
                badgesHtml += `<span style="font-size:9px; background: rgba(137,180,250,0.12); color: var(--accent-blue); padding: 1px 4px; border-radius: 3px; margin-left:4px;" title="Todavía no indexado: el tutor aún no puede citarlo"><i class="fa-solid fa-clock"></i> Pendiente</span>`;
            }

            item.innerHTML = `
                <div style="display:flex; align-items:center; gap:8px;">
                    <i class="fa-solid ${iconClass}" style="color:${iconColor}; font-size:1.1rem;"></i>
                    <div style="flex:1; overflow:hidden;">
                        <div class="book-item-title" style="font-weight:600; font-size:12px; color:var(--text-main); text-overflow:ellipsis; white-space:nowrap; overflow:hidden;"></div>
                        <div style="font-size:10px; color:var(--text-muted); display:flex; justify-content:space-between; margin-top:2px;">
                            <span style="color:var(--accent-blue); font-size:9px; font-weight:bold;">${cat}</span>
                            ${badgesHtml}
                        </div>
                    </div>
                </div>
            `;
            // textContent: un nombre de archivo con < o comillas rompía el marcado
            item.querySelector('.book-item-title').textContent = b.title || b.filename || '(sin nombre)';
            item.title = b.uid || b.filename || '';

            item.onclick = () => {
                this.openBook(key);
                this.renderBooksList(books);
            };
            this.booksListContainer.appendChild(item);
        });
    }


    async openBook(bookId) {
        this.currentBook = bookId;
        const bookObj = this.allBooks.find(b => this.bookKey(b) === bookId);
        
        if (this.statusEl) {
            if (bookObj && bookObj.analysis_failed) {
                this.statusEl.innerHTML = `<span style="color: var(--accent-red);"><i class="fa-solid fa-triangle-exclamation"></i> El análisis falló — vuelve a intentarlo</span>`;
            } else if (bookObj && bookObj.analyzed) {
                this.statusEl.innerHTML = `<span style="color: var(--accent-yellow);"><i class="fa-solid fa-sparkles"></i> Ficha IA Lista</span>`;
            } else {
                this.statusEl.innerHTML = `<span style="color: var(--text-muted);">Sin analizar por IA</span>`;
            }
        }

        // Cargar Visor de Lectura
        this.loadBookViewer(bookId);

        // Cargar o mostrar Metadatos IA
        if (bookObj && bookObj.metadata) {
            this.renderMetadataCard(bookObj.metadata);
        } else {
            this.fetchAndRenderMetadata(bookId);
        }
    }

    async fetchAndRenderMetadata(bookId) {
        if (!this.metadataPane) return;
        try {
            const res = await fetch(`/api/books/metadata?id=${encodeURIComponent(bookId)}`);
            if (res.ok) {
                const meta = await res.json();
                this.renderMetadataCard(meta);
            } else {
                this.renderUnanalyzedState(bookId);
            }
        } catch (e) {
            this.renderUnanalyzedState(bookId);
        }
    }

    renderUnanalyzedState(bookId) {
        if (!this.metadataPane) return;
        this.metadataPane.innerHTML = `
            <div style="padding: 40px; text-align: center; color: var(--text-muted);">
                <i class="fa-solid fa-brain" style="font-size: 40px; color: var(--accent-yellow); margin-bottom: 16px; opacity: 0.7;"></i>
                <h3 style="color: #fff; margin-bottom: 8px;">Documento Listo para Análisis IA</h3>
                <p style="font-size: 13px; max-width: 450px; margin: 0 auto 16px auto;">Haz clic en el botón <strong>"Analizar con IA (JSON)"</strong> arriba para extraer automáticamente los conceptos, temas, lenguajes, nivel y código de práctica.</p>
                <button class="tool-btn btn-primary" onclick="if(window.bookLibraryMgr) window.bookLibraryMgr.analyzeCurrentDocument();" style="background: rgba(249,226,175,0.2); color: var(--accent-yellow); border-color: rgba(249,226,175,0.4); padding: 8px 16px;">
                    <i class="fa-solid fa-wand-magic-sparkles"></i> Iniciar Análisis con Ollama IA
                </button>
            </div>
        `;
    }

    renderMetadataCard(meta) {
        if (!this.metadataPane) return;


        const catName = (meta.category || meta.type || 'KNOWLEDGE').toUpperCase();
        const categoryBadge = `<span style="background: rgba(203,166,247,0.2); color: var(--accent-purple); padding: 3px 8px; border-radius: 12px; font-size: 11px; font-weight: bold;"><i class="fa-solid fa-layer-group"></i> ${catName}</span>`;

        const levelBadge = meta.level ? `<span style="background: rgba(166,227,161,0.2); color: var(--accent-green); padding: 3px 8px; border-radius: 12px; font-size: 11px; font-weight: bold; text-transform: uppercase;">Nivel: ${meta.level}</span>` : '';
        const typeBadge = meta.type ? `<span style="background: rgba(137,180,250,0.2); color: var(--accent-blue); padding: 3px 8px; border-radius: 12px; font-size: 11px; text-transform: uppercase;">${meta.type}</span>` : '';
        const datasetBadge = meta.dataset && meta.dataset !== 'Ninguno' && meta.dataset !== 'Sin Dataset' && meta.dataset !== 'N/A' ? `<span style="background: rgba(249,226,175,0.2); color: var(--accent-yellow); padding: 3px 8px; border-radius: 12px; font-size: 11px;"><i class="fa-solid fa-database"></i> ${meta.dataset}</span>` : '';
        
        const topicsTags = (meta.topics || []).map(t => `<span style="background: var(--bg-panel); border: 1px solid var(--border-color); color: var(--accent-yellow); padding: 2px 8px; border-radius: 4px; font-size: 11px;">#${t}</span>`).join(' ');
        const conceptsTags = (meta.concepts || []).map(c => `<span style="background: var(--bg-panel); border: 1px solid var(--border-color); color: var(--accent-purple); padding: 2px 8px; border-radius: 4px; font-size: 11px;">💡 ${c}</span>`).join(' ');
        const libsTags = (meta.libraries || []).map(lib => `<span style="background: rgba(137,180,250,0.15); color: var(--accent-blue); padding: 2px 8px; border-radius: 4px; font-size: 11px;">📦 ${lib}</span>`).join(' ');
        const depsTags = (meta.dependencies || []).map(d => `<span style="background: var(--bg-panel); border: 1px solid var(--border-color); color: var(--accent-blue); padding: 2px 8px; border-radius: 4px; font-size: 11px;">🔗 ${d}</span>`).join(' ');
        const langsTags = (meta.languages || []).map(l => `<span style="background: rgba(166,227,161,0.15); color: var(--accent-green); padding: 2px 8px; border-radius: 4px; font-size: 11px;">💻 ${l}</span>`).join(' ');

        const takeawaysList = (meta.key_takeaways || []).map(k => `<li style="margin-bottom: 4px;">${k}</li>`).join('');

        let codeExamplesHtml = '';
        if (meta.code_examples && meta.code_examples.length > 0) {
            codeExamplesHtml = meta.code_examples.map(code => `
                <div style="margin-top: 10px; background: var(--bg-dark); border: 1px solid var(--border-color); border-radius: 6px; padding: 10px;">
                    <pre style="margin: 0; font-family: 'Fira Code', monospace; font-size: 12px; color: #a6e3a1; white-space: pre-wrap;">${code}</pre>
                </div>
            `).join('');
        }

        const jsonFormattedStr = JSON.stringify(meta, null, 2);

        this.metadataPane.innerHTML = `
            <div style="max-width: 900px; margin: 0 auto; display: flex; flex-direction: column; gap: 16px;">
                
                <!-- Encabezado de la Ficha -->
                <div style="background: var(--bg-panel); border: 1px solid var(--border-color); border-radius: 8px; padding: 16px;">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px;">
                        <h2 style="margin: 0; color: #fff; font-size: 18px;"><i class="fa-solid fa-file-invoice" style="color: var(--accent-purple); margin-right: 8px;"></i> ${meta.title || meta.filename}</h2>
                        <div style="display: flex; gap: 6px;">
                            ${categoryBadge}
                            ${typeBadge}
                            ${levelBadge}
                            ${datasetBadge}
                        </div>
                    </div>
                </div>
                    <div style="font-size: 11px; color: var(--text-muted); margin-bottom: 12px;">
                        <span><i class="fa-solid fa-file"></i> Archivo: ${meta.filename}</span> · 
                        <span><i class="fa-solid fa-calendar"></i> Analizado: ${meta.created_at ? meta.created_at.split('T')[0] : 'Reciente'}</span>
                    </div>

                    <!-- Tags de Clasificación -->
                    <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px;">
                        ${langsTags}
                        ${libsTags}
                        ${topicsTags}
                        ${conceptsTags}
                    </div>
                </div>


                <!-- Resumen y Puntos Clave -->
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px;">
                    <div style="background: var(--bg-panel); border: 1px solid var(--border-color); border-radius: 8px; padding: 14px;">
                        <h4 style="margin-top: 0; font-size: 13px; color: var(--accent-yellow); border-bottom: 1px solid var(--border-color); padding-bottom: 6px;"><i class="fa-solid fa-align-left"></i> Resumen Estructurado</h4>
                        <p style="font-size: 12px; line-height: 1.6; color: var(--text-main); margin: 0;">${meta.summary || 'Sin resumen disponible.'}</p>
                    </div>

                    <div style="background: var(--bg-panel); border: 1px solid var(--border-color); border-radius: 8px; padding: 14px;">
                        <h4 style="margin-top: 0; font-size: 13px; color: var(--accent-green); border-bottom: 1px solid var(--border-color); padding-bottom: 6px;"><i class="fa-solid fa-bullseye"></i> Puntos Clave / Key Takeaways</h4>
                        <ul style="font-size: 12px; line-height: 1.6; color: var(--text-main); margin: 0; padding-left: 16px;">
                            ${takeawaysList || '<li>Revisar contenido del documento.</li>'}
                        </ul>
                    </div>
                </div>

                <!-- Prerrequisitos y Dependencias -->
                ${depsTags ? `
                <div style="background: var(--bg-panel); border: 1px solid var(--border-color); border-radius: 8px; padding: 14px;">
                    <h4 style="margin-top: 0; font-size: 13px; color: var(--accent-blue); margin-bottom: 8px;"><i class="fa-solid fa-cubes"></i> Prerrequisitos & Dependencias Recomendadas</h4>
                    <div style="display: flex; flex-wrap: wrap; gap: 6px;">${depsTags}</div>
                </div>` : ''}

                <!-- Ejemplos de Código -->
                ${codeExamplesHtml ? `
                <div style="background: var(--bg-panel); border: 1px solid var(--border-color); border-radius: 8px; padding: 14px;">
                    <h4 style="margin-top: 0; font-size: 13px; color: var(--accent-green); margin-bottom: 4px;"><i class="fa-solid fa-code"></i> Ejemplos de Código / Práctica Derivada</h4>
                    ${codeExamplesHtml}
                </div>` : ''}

                <!-- JSON Estructurado Crudo -->
                <div style="background: var(--bg-panel); border: 1px solid var(--border-color); border-radius: 8px; padding: 14px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <h4 style="margin: 0; font-size: 13px; color: var(--text-muted);"><i class="fa-solid fa-code-compare"></i> Estructura JSON Metadatos Guardada (~/.prig_books/metadata/)</h4>
                        <button class="tool-btn" onclick="navigator.clipboard.writeText(\`${jsonFormattedStr.replace(/`/g, '\\`')}\`); alert('JSON copiado al portapapeles!');" style="font-size: 11px; padding: 3px 8px;"><i class="fa-solid fa-copy"></i> Copiar JSON</button>
                    </div>
                    <pre style="margin: 0; background: var(--bg-dark); border: 1px solid var(--border-color); padding: 12px; border-radius: 6px; font-family: 'Fira Code', monospace; font-size: 11px; color: var(--accent-yellow); overflow-x: auto; max-height: 250px;">${jsonFormattedStr}</pre>
                </div>

            </div>
        `;
    }

    async analyzeCurrentDocument() {
        if (!this.currentBook) {
            alert('Selecciona un libro o documento de la lista primero.');
            return;
        }

        if (this.statusEl) {
            this.statusEl.innerHTML = `<span style="color: var(--accent-yellow);"><i class="fa-solid fa-spinner fa-spin"></i> Analizando con Ollama IA...</span>`;
        }

        if (this.metadataPane) {
            this.metadataPane.innerHTML = `
                <div style="padding: 60px; text-align: center; color: var(--text-muted);">
                    <i class="fa-solid fa-wand-magic-sparkles fa-bounce" style="font-size: 44px; color: var(--accent-yellow); margin-bottom: 16px;"></i>
                    <h3 style="color: #fff; margin-bottom: 8px;">Ollama IA está analizando "${this.currentBookTitle()}"...</h3>
                    <p style="font-size: 13px; max-width: 450px; margin: 0 auto;">Extrayendo automáticamente temas, conceptos, lenguajes, nivel y código estructurado JSON...</p>
                </div>
            `;
        }

        try {
            // Respetar el modelo elegido en la configuración global en vez de fijarlo
            const model = (window.aiConfig && window.aiConfig.agent1_model) || 'qwen2.5-coder:7b';
            const res = await fetch('/api/books/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ book_id: this.currentBook, model })
            });

            const meta = prigJson(res);
            if (meta.error) throw new Error(meta.error);

            // El backend ya no finge éxito cuando el modelo falla: lo marca
            if (meta.analysis_failed) {
                throw new Error(meta.analysis_error || 'El modelo no devolvió una ficha válida.');
            }

            this.renderMetadataCard(meta);
            await this.loadBooks();

            if (this.statusEl) {
                this.statusEl.innerHTML = `<span style="color: var(--accent-green);"><i class="fa-solid fa-circle-check"></i> Ficha IA Generada</span>`;
            }
        } catch (e) {
            console.error("Error analizando documento:", e);
            alert("Error al analizar documento con IA: " + e.message);
            this.renderUnanalyzedState(this.currentBook);
        }
    }

    async importDocumentFile() {
        const path = prompt("Ingresa la ruta completa del archivo PDF o código a importar a tu biblioteca:", "~/Documentos/mi_libro.pdf");
        if (!path || !path.trim()) return;

        try {
            const res = await fetch('/api/books/import', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: path.trim() })
            });
            const data = prigJson(res);
            if (data.error) throw new Error(data.error);

            alert(`Documento importado con éxito a ~/.prig_books/${data.filename}`);
            await this.loadBooks();
            const newKey = data.uid || data.id;
            if (newKey) this.openBook(newKey);
            this.refreshIndexStatus();
        } catch (e) {
            alert("Error importando documento: " + e.message);
        }
    }

    async loadBookViewer(bookId) {
        if (!this.viewerContainer) return;
        try {
            const res = await fetch(`/api/books/read?id=${encodeURIComponent(bookId)}`);
            const data = await res.json();

            if (data.error) {
                this.viewerContainer.innerHTML = `<div style="padding:20px; color:var(--accent-red);">${data.error}</div>`;
                return;
            }

            if (data.type === 'pdf') {
                this.renderPdfViewer(data.url);
            } else {
                this.renderTextViewer(data.content);
            }
        } catch (e) {
            console.error("Error abriendo libro:", e);
            this.viewerContainer.innerHTML = `<div style="padding:20px; color:var(--accent-red);">Error leyendo libro: ${e.message}</div>`;
        }
    }

    renderTextViewer(content) {
        let html = '';
        if (typeof marked !== 'undefined') {
            html = marked.parse(content);
        } else {
            html = `<pre style="white-space:pre-wrap;">${content}</pre>`;
        }

        this.viewerContainer.innerHTML = `
            <div style="padding:20px; max-width:800px; margin:0 auto; line-height:1.7;" class="markdown-body">
                ${html}
            </div>
        `;
    }

    renderPdfViewer(pdfUrl) {
        this.viewerContainer.innerHTML = `
            <div style="display:flex; flex-direction:column; height:100%;">
                <div style="padding:8px 12px; background:var(--bg-dark); border-bottom:1px solid var(--border-color); display:flex; gap:10px; align-items:center; font-size:12px;">
                    <span>Vista previa del documento PDF</span>
                    <button class="tool-btn" onclick="window.open('${pdfUrl}', '_blank')"><i class="fa-solid fa-arrow-up-right-from-square"></i> Abrir PDF Externo</button>
                </div>
                <iframe src="${pdfUrl}" style="flex:1; width:100%; border:none;"></iframe>
            </div>
        `;
    }

    async createSnippetFromSelection() {
        if (!this.currentBook) {
            alert('Abre un libro de la biblioteca primero.');
            return;
        }

        const label = prompt("Ingresa una etiqueta para esta cita o recuadre:", "Ecuación / Párrafo clave");
        if (!label) return;

        const selectionText = window.getSelection() ? window.getSelection().toString() : '';

        try {
            const res = await fetch('/api/books/snippet', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    book_id: this.currentBook,
                    page: 1,
                    text: selectionText || `Cita del documento ${this.currentBook}`,
                    label: label
                })
            });

            const snippet = prigJson(res);
            await this.loadSavedSnippets();

            const tag = `\n\n::cite[${snippet.id}]\n\n`;
            if (window.editorMgr && window.editorMgr.insertText) {
                window.editorMgr.insertText(tag);
            } else if (navigator.clipboard) {
                navigator.clipboard.writeText(tag);
                alert(`Cita creada con éxito: ${tag}\n¡Copiada al portapapeles!`);
            }
        } catch (e) {
            console.error("Error creando recorte de libro:", e);
            alert("Error al guardar cita: " + e.message);
        }
    }

    async loadSavedSnippets() {
        if (!this.snippetsContainer) return;
        try {
            const res = await fetch('/api/books/snippets');
            const snippets = await res.json();

            const snippetKeys = Object.keys(snippets);
            if (snippetKeys.length === 0) {
                this.snippetsContainer.innerHTML = '<div style="padding:10px; color:var(--text-muted); font-size:11px;">No hay citas guardadas aún. Marca un pasaje y presiona "Crear Cita".</div>';
                return;
            }

            this.snippetsContainer.innerHTML = '';
            snippetKeys.forEach(k => {
                const snp = snippets[k];
                const item = document.createElement('div');
                item.style.cssText = 'padding:6px 8px; margin-bottom:6px; background:var(--bg-dark); border:1px solid var(--border-color); border-radius:4px; font-size:11px; cursor:pointer;';
                item.innerHTML = `
                    <div style="font-weight:bold; color:var(--accent-purple); display:flex; justify-content:space-between;">
                        <span>${snp.label}</span>
                        <span style="font-size:10px; opacity:0.7;">${snp.cite_tag}</span>
                    </div>
                    <div style="color:var(--text-muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; margin-top:2px;">${snp.text}</div>
                `;
                item.onclick = () => {
                    if (navigator.clipboard) {
                        navigator.clipboard.writeText(snp.cite_tag);
                        alert(`Etiqueta de cita copiada: ${snp.cite_tag}`);
                    }
                };
                this.snippetsContainer.appendChild(item);
            });
        } catch (e) {
            console.error("Error cargando recortes:", e);
        }
    }
}

window.bookLibraryMgr = new BookLibraryManager();

document.addEventListener('DOMContentLoaded', () => {
    if (!window.bookLibraryMgr) {
        window.bookLibraryMgr = new BookLibraryManager();
    }
});
