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

        this.libreriasPane = document.getElementById('pane-book-librerias');
        this.libreriasContainer = document.getElementById('librerias-viewer-content');
        this.currentPdfPage = 1;
        this.currentPdfTotalPages = 1;
        this.pdfReaderMode = 'text'; // 'text' o 'iframe'
        this.currentPdfData = null;
        this.currentCitations = null;
        this.currentLibrary = null;
        this.librariesList = [];

        this.activeCategory = 'ALL';
        this.initEvents();
    }

    initEvents() {
        const btnClose = document.getElementById('btn-close-book-library');
        if (btnClose) btnClose.onclick = () => this.closeModal();

        const btnRefresh = document.getElementById('btn-refresh-books');
        if (btnRefresh) btnRefresh.onclick = () => {
            if (this.activeCategory === 'librerias') this.loadLibrariesList();
            else this.loadBooks();
        };

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
            this.searchInput.oninput = () => {
                const q = this.searchInput.value.trim().toLowerCase();
                if (this.activeCategory === 'librerias') {
                    this.filterLibrariesList(q);
                } else {
                    this.filterBooksList(q);
                }
            };
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
            clickedBtn.style.background = cat === 'librerias' ? 'var(--accent-green)' : 'var(--accent-purple)';
            clickedBtn.style.color = '#111';
            clickedBtn.style.fontWeight = 'bold';
            clickedBtn.style.border = 'none';
        }

        if (cat === 'librerias') {
            this.loadLibrariesList();
        } else {
            this.filterBooksList(this.searchInput ? this.searchInput.value.trim().toLowerCase() : '');
        }
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
        const btnLibs = document.getElementById('tab-btn-book-librerias');

        [btnMeta, btnReader, btnLibs].forEach(b => { if (b) b.classList.remove('active'); });
        if (this.metadataPane) this.metadataPane.style.display = 'none';
        if (this.readerPane) this.readerPane.style.display = 'none';
        if (this.libreriasPane) this.libreriasPane.style.display = 'none';

        if (tabName === 'metadata') {
            if (btnMeta) btnMeta.classList.add('active');
            if (this.metadataPane) this.metadataPane.style.display = 'block';
        } else if (tabName === 'librerias') {
            if (btnLibs) btnLibs.classList.add('active');
            if (this.libreriasPane) this.libreriasPane.style.display = 'block';
        } else {
            if (btnReader) btnReader.classList.add('active');
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

            this.currentBookData = data;
            const ext = (data.path || bookId).split('.').pop().toLowerCase();

            if (data.type === 'pdf' || ext === 'pdf') {
                if (this.pdfReaderMode === 'text') {
                    await this.loadPdfReaderAndCitations(bookId, 1);
                } else {
                    this.renderPdfIframeViewer(data.url);
                }
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
            <div style="display: flex; flex-direction: column; height: 100%;">
                <div style="padding: 8px 12px; background: rgba(0,0,0,0.25); border-bottom: 1px solid var(--border-color); display: flex; justify-content: space-between; align-items: center; font-size: 12px;">
                    <span style="color: var(--accent-blue); font-weight: bold;"><i class="fa-solid fa-file-lines"></i> Lector de Texto</span>
                    <div style="display: flex; gap: 8px;">
                        <button class="tool-btn" onclick="window.bookLibraryMgr.createCitationPrompt();" style="background: rgba(203,166,247,0.15); color: var(--accent-purple); border-color: rgba(203,166,247,0.3); font-size: 11px;">
                            <i class="fa-solid fa-quote-left"></i> Guardar Cita de Selección
                        </button>
                    </div>
                </div>
                <div style="flex: 1; overflow: auto; padding: 20px; line-height: 1.7;" class="markdown-body">
                    ${html}
                </div>
            </div>
        `;
    }

    renderPdfIframeViewer(pdfUrl) {
        this.viewerContainer.innerHTML = `
            <div style="display:flex; flex-direction:column; height:100%;">
                <div style="padding:8px 12px; background:var(--bg-dark); border-bottom:1px solid var(--border-color); display:flex; justify-content:space-between; align-items:center; font-size:12px;">
                    <div style="display:flex; gap:10px; align-items:center;">
                        <span style="font-weight:bold; color:var(--accent-purple);">Vista Previa PDF</span>
                        <button class="tool-btn" onclick="window.bookLibraryMgr.togglePdfMode('text')" style="background: rgba(137,180,250,0.15); color: var(--accent-blue); font-size: 11px;">
                            <i class="fa-solid fa-file-pen"></i> Cambiar a Editor de Texto y Citas
                        </button>
                    </div>
                    <button class="tool-btn" onclick="window.open('${pdfUrl}', '_blank')"><i class="fa-solid fa-arrow-up-right-from-square"></i> Abrir PDF Externo</button>
                </div>
                <iframe src="${pdfUrl}" style="flex:1; width:100%; border:none;"></iframe>
            </div>
        `;
    }

    togglePdfMode(mode) {
        this.pdfReaderMode = mode;
        if (this.currentBook) {
            this.loadBookViewer(this.currentBook);
        }
    }

    // =========================================================================
    // LECTOR Y EDITOR DE TEXTO PDF + CITAS (<nombre_libro>.json)
    // =========================================================================

    async loadPdfReaderAndCitations(bookId, page = 1, searchQuery = '') {
        if (!this.viewerContainer) return;
        this.viewerContainer.innerHTML = `<div style="padding:30px; text-align:center; color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin fa-2x"></i><br><br>Cargando texto del libro y citas...</div>`;

        try {
            const [pagesRes, citasRes] = await Promise.all([
                fetch(`/api/books/pdf-pages?id=${encodeURIComponent(bookId)}&page=${page}&search=${encodeURIComponent(searchQuery)}`),
                fetch(`/api/books/citations?id=${encodeURIComponent(bookId)}`)
            ]);

            const pageData = await pagesRes.json();
            const citationsData = await citasRes.json();

            if (pageData.error) {
                this.viewerContainer.innerHTML = `<div style="padding:20px; color:var(--accent-red);">${pageData.error}</div>`;
                return;
            }

            this.currentPdfData = pageData;
            this.currentCitations = citationsData;
            this.currentPdfPage = pageData.current_page || 1;
            this.currentPdfTotalPages = pageData.total_pages || 1;

            this.renderPdfTextAndCitationsView(pageData, citationsData);
        } catch (e) {
            console.error("Error cargando páginas PDF y citas:", e);
            this.viewerContainer.innerHTML = `<div style="padding:20px; color:var(--accent-red);">Error: ${e.message}</div>`;
        }
    }

    renderPdfTextAndCitationsView(pageData, citationsData) {
        const total = pageData.total_pages || 1;
        const curr = pageData.current_page || 1;
        const stem = pageData.stem || 'libro';
        const citas = (citationsData && citationsData.citas) || [];
        const jsonFileName = citationsData.archivo_json || `${stem}.json`;

        // Renderizar lista de citas guardadas
        let citasListHtml = '';
        if (citas.length === 0) {
            citasListHtml = `
                <div style="padding: 20px; text-align: center; color: var(--text-muted); font-size: 11px;">
                    <i class="fa-solid fa-quote-left" style="font-size: 24px; opacity: 0.5; margin-bottom: 8px;"></i>
                    <p style="margin: 0;">No hay citas guardadas aún en <code>${jsonFileName}</code>.</p>
                    <p style="margin: 4px 0 0 0; opacity: 0.8;">Selecciona cualquier texto en el editor a la izquierda y haz clic en <strong>"Guardar Selección como Cita"</strong>.</p>
                </div>
            `;
        } else {
            citasListHtml = citas.map(c => `
                <div class="cita-card" style="background: var(--bg-dark); border: 1px solid var(--border-color); border-radius: 6px; padding: 10px; display: flex; flex-direction: column; gap: 6px; transition: border-color 0.2s ease;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="background: rgba(137,180,250,0.15); color: var(--accent-blue); padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: bold; cursor: pointer;" onclick="window.bookLibraryMgr.loadPdfReaderAndCitations('${pageData.id}', ${c.pagina});" title="Ir a la página ${c.pagina}">
                            <i class="fa-solid fa-bookmark"></i> Pág. ${c.pagina}
                        </span>
                        <span style="font-size: 10px; color: var(--text-muted);">${(c.fecha || '').split('T')[0]}</span>
                    </div>

                    <blockquote style="margin: 0; padding: 4px 8px; border-left: 2px solid var(--accent-purple); font-size: 11px; color: var(--text-main); font-style: italic; background: rgba(203,166,247,0.05); border-radius: 0 4px 4px 0; max-height: 100px; overflow-y: auto;">
                        "${c.texto}"
                    </blockquote>

                    ${c.nota ? `<div style="font-size: 11px; color: var(--accent-yellow);"><i class="fa-solid fa-note-sticky"></i> ${c.nota}</div>` : ''}

                    ${c.tags && c.tags.length > 0 ? `
                        <div style="display: flex; flex-wrap: wrap; gap: 4px;">
                            ${c.tags.map(t => `<span style="font-size: 9px; background: rgba(255,255,255,0.06); color: var(--text-muted); padding: 1px 4px; border-radius: 3px;">#${t}</span>`).join('')}
                        </div>
                    ` : ''}

                    <div style="display: flex; justify-content: flex-end; gap: 6px; margin-top: 4px; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 4px;">
                        <button class="tool-btn" style="font-size: 10px; padding: 2px 6px; background: rgba(137,180,250,0.15); color: var(--accent-blue);" onclick="window.bookLibraryMgr.askChatWithCitation(${JSON.stringify(c).replace(/"/g, '&quot;')});" title="Pedir al modelo de IA que razone con esta cita">
                            <i class="fa-solid fa-brain"></i> Preguntar al Chat
                        </button>
                        <button class="tool-btn" style="font-size: 10px; padding: 2px 6px;" onclick="navigator.clipboard.writeText(\`> \"${c.texto.replace(/`/g, '\\`')}\"\\n\\n(Fuente: ${pageData.title}, Pág. ${c.pagina})\`); alert('Cita copiada en Markdown');" title="Copiar cita">
                            <i class="fa-solid fa-copy"></i>
                        </button>
                        <button class="tool-btn" style="font-size: 10px; padding: 2px 6px; color: var(--accent-red);" onclick="window.bookLibraryMgr.deleteBookCitation('${c.id}');" title="Eliminar cita">
                            <i class="fa-solid fa-trash"></i>
                        </button>
                    </div>
                </div>
            `).join('');
        }

        // Búsqueda matches dropdown si hay
        let searchDropdownHtml = '';
        if (pageData.search_matches && pageData.search_matches.length > 0) {
            searchDropdownHtml = `
                <div style="margin-top: 6px; padding: 6px; background: rgba(0,0,0,0.3); border: 1px solid var(--border-color); border-radius: 4px; font-size: 11px; max-height: 120px; overflow-y: auto;">
                    <div style="font-weight: bold; color: var(--accent-yellow); margin-bottom: 4px;">${pageData.search_matches.length} coincidencias encontradas:</div>
                    ${pageData.search_matches.map(m => `
                        <div style="cursor: pointer; padding: 3px 6px; border-radius: 3px; margin-bottom: 2px; background: var(--bg-dark);" onclick="window.bookLibraryMgr.loadPdfReaderAndCitations('${pageData.id}', ${m.page});">
                            <span style="color: var(--accent-blue); font-weight: bold;">Pág. ${m.page}:</span> <span style="color: var(--text-muted);">${m.snippet}</span>
                        </div>
                    `).join('')}
                </div>
            `;
        }

        this.viewerContainer.innerHTML = `
            <div style="display: flex; flex-direction: column; height: 100%;">
                
                <!-- Barra Superior de Navegación y Herramientas del Lector -->
                <div style="padding: 8px 12px; background: rgba(0,0,0,0.25); border-bottom: 1px solid var(--border-color); display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
                    
                    <!-- Paginador -->
                    <div style="display: flex; align-items: center; gap: 6px;">
                        <button class="tool-btn" ${curr <= 1 ? 'disabled style="opacity:0.4;"' : ''} onclick="window.bookLibraryMgr.loadPdfReaderAndCitations('${pageData.id}', ${curr - 1});" title="Página anterior">
                            <i class="fa-solid fa-chevron-left"></i>
                        </button>
                        <span style="font-size: 12px; color: var(--text-main);">
                            Página <input type="number" id="input-pdf-page-num" value="${curr}" min="1" max="${total}" style="width: 50px; padding: 2px 4px; background: var(--bg-dark); border: 1px solid var(--border-color); color: #fff; border-radius: 4px; text-align: center;" onkeydown="if(event.key==='Enter') window.bookLibraryMgr.loadPdfReaderAndCitations('${pageData.id}', parseInt(this.value)||1);"> de <b>${total}</b>
                        </span>
                        <button class="tool-btn" ${curr >= total ? 'disabled style="opacity:0.4;"' : ''} onclick="window.bookLibraryMgr.loadPdfReaderAndCitations('${pageData.id}', ${curr + 1});" title="Página siguiente">
                            <i class="fa-solid fa-chevron-right"></i>
                        </button>
                    </div>

                    <!-- Buscador en el PDF -->
                    <div style="display: flex; align-items: center; gap: 4px;">
                        <input type="text" id="input-pdf-search" placeholder="🔍 Buscar en libro..." style="padding: 3px 8px; font-size: 11px; background: var(--bg-dark); border: 1px solid var(--border-color); color: #fff; border-radius: 4px; width: 140px;" onkeydown="if(event.key==='Enter') window.bookLibraryMgr.searchInPdf(this.value);">
                        <button class="tool-btn" style="font-size: 11px; padding: 3px 6px;" onclick="window.bookLibraryMgr.searchInPdf(document.getElementById('input-pdf-search').value);">Buscar</button>
                    </div>

                    <!-- Acciones del Editor y Citas -->
                    <div style="display: flex; gap: 6px; align-items: center;">
                        <button class="tool-btn" style="font-size: 11px; padding: 4px 8px; background: rgba(203,166,247,0.15); color: var(--accent-purple); border-color: rgba(203,166,247,0.3);" onclick="window.bookLibraryMgr.createCitationPrompt();" title="Guardar el texto seleccionado o la página en ${jsonFileName}">
                            <i class="fa-solid fa-quote-left"></i> Guardar Cita de Selección
                        </button>
                        <button class="tool-btn" style="font-size: 11px; padding: 4px 8px; background: rgba(166,227,161,0.15); color: var(--accent-green); border-color: rgba(166,227,161,0.3);" onclick="window.bookLibraryMgr.saveCurrentPageEdit();" title="Guardar correcciones al texto extraído de la página actual">
                            <i class="fa-solid fa-floppy-disk"></i> Guardar Corrección
                        </button>
                        <button class="tool-btn" style="font-size: 11px; padding: 4px 8px;" onclick="window.bookLibraryMgr.exportBookCitations();" title="Exportar ${jsonFileName} a la carpeta del proyecto">
                            <i class="fa-solid fa-file-export"></i> Exportar al Proyecto
                        </button>
                        <button class="tool-btn" style="font-size: 11px; padding: 4px 8px;" onclick="window.bookLibraryMgr.togglePdfMode('preview')" title="Ver PDF original en iframe">
                            <i class="fa-solid fa-file-pdf"></i> Vista PDF
                        </button>
                    </div>

                </div>

                ${searchDropdownHtml ? `<div style="padding: 0 12px;">${searchDropdownHtml}</div>` : ''}

                <!-- Cuerpo Principal: Editor de Texto a la izquierda (flex 3), Citas a la derecha (flex 2) -->
                <div style="flex: 1; display: flex; overflow: hidden; background: var(--bg-dark);">
                    
                    <!-- Columna Izquierda: Editor / Lector de Texto de la Página -->
                    <div style="flex: 3; display: flex; flex-direction: column; border-right: 1px solid var(--border-color); padding: 12px; overflow: hidden;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                            <span style="font-size: 12px; font-weight: bold; color: var(--accent-blue);">
                                <i class="fa-solid fa-file-lines"></i> Texto extraído de la Página ${curr} ${pageData.has_edit ? '<span style="color:var(--accent-yellow); font-size:10px; font-weight:normal;">(editado manualmente)</span>' : ''}
                            </span>
                            <span style="font-size: 11px; color: var(--text-muted);">Selecciona texto para citar o edita erratas de OCR</span>
                        </div>
                        <textarea id="pdf-page-text-editor" style="flex: 1; width: 100%; resize: none; background: #11111b; border: 1px solid var(--border-color); border-radius: 6px; padding: 12px; font-family: 'Fira Code', monospace; font-size: 12px; line-height: 1.6; color: #cdd6f4; outline: none;">${pageData.page_text || ''}</textarea>
                    </div>

                    <!-- Columna Derecha: Citas del Libro (<nombre_libro>.json) -->
                    <div style="flex: 2; display: flex; flex-direction: column; padding: 12px; overflow: hidden; background: var(--bg-panel);">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; border-bottom: 1px solid var(--border-color); padding-bottom: 8px;">
                            <div>
                                <h4 style="margin: 0; font-size: 13px; color: #fff; display: flex; align-items: center; gap: 6px;">
                                    <i class="fa-solid fa-quote-left" style="color: var(--accent-purple);"></i> Citas del Libro
                                </h4>
                                <span style="font-size: 10px; color: var(--accent-yellow); font-family: monospace;">${jsonFileName} (${citas.length} citas)</span>
                            </div>
                            <button class="tool-btn" style="font-size: 10px; padding: 3px 6px;" onclick="window.bookLibraryMgr.createCitationPrompt();">
                                <i class="fa-solid fa-plus"></i> Nueva Cita
                            </button>
                        </div>

                        <div id="pdf-citations-list" style="flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; padding-right: 4px;">
                            ${citasListHtml}
                        </div>
                    </div>

                </div>

            </div>
        `;
    }

    searchInPdf(query) {
        if (!query || !query.trim()) return;
        this.loadPdfReaderAndCitations(this.currentBook, this.currentPdfPage, query.trim());
    }

    async saveCurrentPageEdit() {
        if (!this.currentBook) return;
        const textarea = document.getElementById('pdf-page-text-editor');
        if (!textarea) return;

        const text = textarea.value;
        try {
            const res = await fetch('/api/books/pdf-page-save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    book_id: this.currentBook,
                    page: this.currentPdfPage,
                    text: text
                })
            });
            const data = await res.json();
            if (data.error) throw new Error(data.error);
            alert(`Página ${this.currentPdfPage} guardada con éxito.`);
        } catch (e) {
            alert(`Error guardando corrección: ${e.message}`);
        }
    }

    createCitationPrompt() {
        if (!this.currentBook) {
            alert('Abre un libro de la biblioteca primero.');
            return;
        }

        // Obtener selección del textarea o de la ventana
        let selection = '';
        const textarea = document.getElementById('pdf-page-text-editor');
        if (textarea && textarea.selectionStart !== textarea.selectionEnd) {
            selection = textarea.value.substring(textarea.selectionStart, textarea.selectionEnd).trim();
        } else if (window.getSelection()) {
            selection = window.getSelection().toString().trim();
        }

        if (!selection && textarea) {
            selection = textarea.value.substring(0, 300).trim();
        }

        const nota = prompt("Ingresa una nota de estudio o comentario explicativo para esta cita (opcional):", "Concepto fundamental para razonar");
        if (nota === null) return;

        const tagsStr = prompt("Etiquetas/Tags separados por comas (ej: algebra, tensores, backpropagation):", "teoria, deep-learning");
        const tags = (tagsStr || "").split(',').map(t => t.trim()).filter(Boolean);

        const citaData = {
            pagina: this.currentPdfPage || 1,
            capitulo: `Página ${this.currentPdfPage}`,
            texto: selection || `Cita de la página ${this.currentPdfPage}`,
            nota: nota,
            tags: tags
        };

        this.saveBookCitation(citaData);
    }

    async saveBookCitation(citaData) {
        try {
            const res = await fetch('/api/books/citations/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    book_id: this.currentBook,
                    citation: citaData
                })
            });
            const data = await res.json();
            if (data.error) throw new Error(data.error);

            alert(`Cita guardada con éxito en ${data.archivo_json}`);
            await this.loadPdfReaderAndCitations(this.currentBook, this.currentPdfPage);
        } catch (e) {
            alert(`Error guardando cita: ${e.message}`);
        }
    }

    async deleteBookCitation(citationId) {
        if (!confirm('¿Eliminar esta cita del archivo JSON?')) return;
        try {
            const res = await fetch('/api/books/citations/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    book_id: this.currentBook,
                    citation_id: citationId
                })
            });
            const data = await res.json();
            if (data.error) throw new Error(data.error);
            await this.loadPdfReaderAndCitations(this.currentBook, this.currentPdfPage);
        } catch (e) {
            alert(`Error eliminando cita: ${e.message}`);
        }
    }

    async exportBookCitations() {
        if (!this.currentBook) return;
        try {
            const res = await fetch('/api/books/citations/export', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    book_id: this.currentBook
                })
            });
            const data = await res.json();
            if (data.error) throw new Error(data.error);
            alert(`¡Archivo exportado con éxito!\n\nSe ha copiado '${data.filename}' (${data.total_citas} citas) a tu espacio de trabajo para que cualquier modelo pueda leerlo directamente.`);
        } catch (e) {
            alert(`Error exportando citas: ${e.message}`);
        }
    }

    askChatWithCitation(cita) {
        const bookTitle = (this.currentPdfData && this.currentPdfData.title) || this.currentBook;
        const promptText = `A partir de la siguiente cita del libro "${bookTitle}" (Pág. ${cita.pagina}):\n\n> "${cita.texto}"\n\n${cita.nota ? 'Nota de estudio: ' + cita.nota + '\n\n' : ''}Por favor, razona a fondo sobre este pasaje y proporciona una explicación didáctica, técnica y completa con ejemplos prácticos.`;

        this.closeModal();
        if (window.app && window.app.sendAIChatMessage) {
            window.app.sendAIChatMessage(promptText, { selected_citations: [cita] });
        } else {
            const chatInput = document.getElementById('chat-input');
            if (chatInput) {
                chatInput.value = promptText;
                chatInput.focus();
            }
        }
    }

    // =========================================================================
    // ANALISTA DE LIBRERÍAS (matplotlib, numpy, pandas, pytorch...)
    // =========================================================================

    async loadLibrariesList() {
        if (!this.booksListContainer) return;
        this.booksListContainer.innerHTML = '<div style="padding:15px; color:var(--text-muted); text-align:center;"><i class="fa-solid fa-spinner fa-spin"></i> Cargando lista de librerías...</div>';

        try {
            const res = await fetch('/api/librerias/list');
            const libs = await res.json();
            this.librariesList = libs || [];
            this.renderLibrariesList(this.librariesList);

            // Seleccionar la primera librería por defecto
            if (this.librariesList.length > 0 && !this.currentLibrary) {
                this.selectLibrary(this.librariesList[0].id);
            }
        } catch (e) {
            console.error("Error cargando librerías:", e);
            this.booksListContainer.innerHTML = `<div style="padding:15px; color:var(--accent-red);">Error: ${e.message}</div>`;
        }
    }

    renderLibrariesList(libs) {
        if (!this.booksListContainer) return;
        this.booksListContainer.innerHTML = `
            <div style="margin-bottom: 8px;">
                <button class="tool-btn" style="width: 100%; font-size: 11px; padding: 6px; background: rgba(166,227,161,0.15); color: var(--accent-green); border-color: rgba(166,227,161,0.3);" onclick="window.bookLibraryMgr.addCustomLibraryPrompt();">
                    <i class="fa-solid fa-plus"></i> Añadir Repositorio GitHub
                </button>
            </div>
        `;

        libs.forEach(lib => {
            const isSelected = this.currentLibrary === lib.id;
            const item = document.createElement('div');
            item.className = `book-item-card ${isSelected ? 'active' : ''}`;
            item.style.cssText = `padding: 8px 10px; border-radius: 6px; cursor: pointer; background: ${isSelected ? 'rgba(166, 227, 161, 0.15)' : 'var(--bg-dark)'}; border: 1px solid ${isSelected ? 'var(--accent-green)' : 'var(--border-color)'}; transition: all 0.2s ease;`;

            item.innerHTML = `
                <div style="display:flex; align-items:center; gap:8px;">
                    <i class="fa-solid fa-boxes-stacked" style="color:${lib.color || 'var(--accent-green)'}; font-size:1.1rem;"></i>
                    <div style="flex:1; overflow:hidden;">
                        <div style="font-weight:600; font-size:12px; color:var(--text-main); text-overflow:ellipsis; white-space:nowrap; overflow:hidden;">${lib.nombre}</div>
                        <div style="font-size:10px; color:var(--text-muted); display:flex; justify-content:space-between; margin-top:2px;">
                            <span style="color:var(--accent-blue); font-size:9px;">${lib.repo}</span>
                            <span style="font-size:9px; background: rgba(249,226,175,0.15); color: var(--accent-yellow); padding: 1px 4px; border-radius: 3px;">
                                ${lib.total_citas} citas
                            </span>
                        </div>
                    </div>
                </div>
            `;
            item.onclick = () => {
                this.selectLibrary(lib.id);
                this.renderLibrariesList(libs);
            };
            this.booksListContainer.appendChild(item);
        });
    }

    filterLibrariesList(query) {
        if (!query) {
            this.renderLibrariesList(this.librariesList);
            return;
        }
        const filtered = this.librariesList.filter(l => 
            l.nombre.toLowerCase().includes(query) || 
            l.repo.toLowerCase().includes(query) ||
            l.descripcion.toLowerCase().includes(query) ||
            (l.tags && l.tags.some(t => t.toLowerCase().includes(query)))
        );
        this.renderLibrariesList(filtered);
    }

    async addCustomLibraryPrompt() {
        const repo = prompt("Ingresa el repositorio de GitHub (formato usuario/repo, ej: huggingface/datasets):", "");
        if (!repo || !repo.trim()) return;

        try {
            const res = await fetch('/api/librerias/add', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ repo: repo.trim() })
            });
            const data = await res.json();
            if (data.error) throw new Error(data.error);

            alert(`¡Librería ${data.library.nombre} añadida con éxito!`);
            await this.loadLibrariesList();
            this.selectLibrary(data.library.id);
        } catch (e) {
            alert(`Error añadiendo librería: ${e.message}`);
        }
    }

    async selectLibrary(libId) {
        this.currentLibrary = libId;
        this.switchTab('librerias');

        if (!this.libreriasContainer) return;
        this.libreriasContainer.innerHTML = `<div style="padding:40px; text-align:center; color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin fa-2x"></i><br><br>Cargando información y citas de la librería...</div>`;

        try {
            const lib = this.librariesList.find(l => l.id === libId) || { id: libId, nombre: libId, repo: libId };
            const res = await fetch(`/api/librerias/citations?id=${encodeURIComponent(libId)}`);
            const citationsData = await res.json();

            this.renderLibraryView(lib, citationsData);
        } catch (e) {
            console.error("Error seleccionando librería:", e);
            this.libreriasContainer.innerHTML = `<div style="padding:20px; color:var(--accent-red);">Error: ${e.message}</div>`;
        }
    }

    renderLibraryView(lib, citationsData) {
        const citas = (citationsData && citationsData.citas) || [];
        const jsonFileName = citationsData.archivo_json || `${lib.id}.json`;

        let citasListHtml = '';
        if (citas.length === 0) {
            citasListHtml = `
                <div style="padding: 20px; text-align: center; color: var(--text-muted); font-size: 11px;">
                    <i class="fa-solid fa-code" style="font-size: 24px; opacity: 0.5; margin-bottom: 8px;"></i>
                    <p style="margin: 0;">No hay recetas ni citas de código guardadas aún en <code>${jsonFileName}</code>.</p>
                    <p style="margin: 4px 0 0 0; opacity: 0.8;">Utiliza el <strong>Analista de APIs con IA</strong> arriba para consultar cualquier función y guardarla con un clic.</p>
                </div>
            `;
        } else {
            citasListHtml = citas.map(c => `
                <div class="lib-cita-card" style="background: var(--bg-dark); border: 1px solid var(--border-color); border-radius: 6px; padding: 12px; display: flex; flex-direction: column; gap: 8px;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-weight: bold; color: var(--accent-green); font-size: 13px;">
                            <i class="fa-solid fa-cube"></i> ${c.tema || c.funcion}
                        </span>
                        <span style="font-size: 10px; color: var(--text-muted); font-family: monospace;">${c.modulo || lib.id}</span>
                    </div>

                    ${c.explicacion ? `<div style="font-size: 12px; color: var(--text-main); line-height: 1.5;">${c.explicacion}</div>` : ''}

                    <div style="background: #11111b; border: 1px solid var(--border-color); border-radius: 4px; padding: 10px;">
                        <pre style="margin: 0; font-family: 'Fira Code', monospace; font-size: 11px; color: #a6e3a1; overflow-x: auto; white-space: pre-wrap;">${c.snippet || '# Sin código'}</pre>
                    </div>

                    ${c.parametros_clave && c.parametros_clave.length > 0 ? `
                        <div style="font-size: 11px; color: var(--accent-yellow);">
                            <strong>Parámetros clave:</strong> ${c.parametros_clave.join(', ')}
                        </div>
                    ` : ''}

                    <div style="display: flex; justify-content: flex-end; gap: 6px; margin-top: 4px; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 6px;">
                        <button class="tool-btn" style="font-size: 10px; padding: 3px 8px; background: rgba(137,180,250,0.15); color: var(--accent-blue);" onclick="window.bookLibraryMgr.askChatWithLibraryCitation(${JSON.stringify(c).replace(/"/g, '&quot;')}, '${lib.nombre}');" title="Pedir al modelo que use esta cita de código">
                            <i class="fa-solid fa-brain"></i> Preguntar al Chat
                        </button>
                        <button class="tool-btn" style="font-size: 10px; padding: 3px 8px;" onclick="navigator.clipboard.writeText(\`${(c.snippet || '').replace(/`/g, '\\`')}\`); alert('Código copiado');" title="Copiar código">
                            <i class="fa-solid fa-copy"></i> Copiar Código
                        </button>
                        <button class="tool-btn" style="font-size: 10px; padding: 3px 8px; color: var(--accent-red);" onclick="window.bookLibraryMgr.deleteLibraryCitation('${lib.id}', '${c.id}');" title="Eliminar cita">
                            <i class="fa-solid fa-trash"></i>
                        </button>
                    </div>
                </div>
            `).join('');
        }

        this.libreriasContainer.innerHTML = `
            <div style="max-width: 950px; margin: 0 auto; display: flex; flex-direction: column; gap: 16px;">
                
                <!-- Encabezado de la Librería -->
                <div style="background: var(--bg-panel); border: 1px solid var(--border-color); border-radius: 8px; padding: 16px;">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px; flex-wrap: wrap; gap: 8px;">
                        <div>
                            <h2 style="margin: 0; color: #fff; font-size: 20px; display: flex; align-items: center; gap: 8px;">
                                <i class="fa-solid fa-boxes-stacked" style="color: ${lib.color || 'var(--accent-green)'};"></i> ${lib.nombre}
                            </h2>
                            <span style="font-size: 11px; color: var(--text-muted); font-family: monospace;">GitHub: ${lib.repo}</span>
                        </div>
                        <div style="display: flex; gap: 6px;">
                            ${lib.doc_url ? `<button class="tool-btn" onclick="window.open('${lib.doc_url}', '_blank');" style="font-size: 11px; padding: 4px 8px;"><i class="fa-solid fa-arrow-up-right-from-square"></i> Documentación Oficial</button>` : ''}
                            <button class="tool-btn" onclick="if(window.GitHubLector) { window.bookLibraryMgr.closeModal(); window.GitHubLector.abrir('${lib.repo}'); }" style="font-size: 11px; padding: 4px 8px; background: rgba(137,180,250,0.15); color: var(--accent-blue);">
                                <i class="fa-brands fa-github"></i> Explorar en GitHub Lector
                            </button>
                            <button class="tool-btn" onclick="window.bookLibraryMgr.exportLibraryCitations('${lib.id}');" style="font-size: 11px; padding: 4px 8px; background: rgba(166,227,161,0.15); color: var(--accent-green);">
                                <i class="fa-solid fa-file-export"></i> Exportar ${jsonFileName}
                            </button>
                        </div>
                    </div>
                    <p style="font-size: 12px; color: var(--text-main); margin: 6px 0 0 0; line-height: 1.5;">${lib.descripcion || ''}</p>
                </div>

                <!-- Sección 1: Analista de APIs con IA -->
                <div style="background: var(--bg-panel); border: 1px solid var(--border-color); border-radius: 8px; padding: 16px;">
                    <h3 style="margin: 0 0 10px 0; font-size: 14px; color: var(--accent-yellow); display: flex; align-items: center; gap: 6px;">
                        <i class="fa-solid fa-wand-magic-sparkles"></i> Analista de APIs y Funciones con IA
                    </h3>
                    <p style="font-size: 12px; color: var(--text-muted); margin: 0 0 10px 0;">
                        Pregunta por cualquier función, método o clase de <strong>${lib.nombre}</strong> (ej: <code>plt.subplots</code>, <code>np.einsum</code>, <code>torch.nn.Conv2d</code>). El modelo extraerá su sintaxis moderna y generará un snippet ejecutable para guardar como cita.
                    </p>
                    <div style="display: flex; gap: 8px;">
                        <input type="text" id="input-lib-analyze-topic" placeholder="Ej: plt.subplots, np.broadcast_to, DataLoader, ColumnTransformer..." style="flex: 1; padding: 8px 12px; background: var(--bg-dark); border: 1px solid var(--border-color); color: #fff; border-radius: 6px; font-size: 12px;" onkeydown="if(event.key==='Enter') window.bookLibraryMgr.runLibraryAnalysis('${lib.id}');">
                        <button class="tool-btn btn-primary" onclick="window.bookLibraryMgr.runLibraryAnalysis('${lib.id}');" style="background: rgba(249,226,175,0.2); color: var(--accent-yellow); border-color: rgba(249,226,175,0.4); padding: 8px 16px;">
                            <i class="fa-solid fa-microscope"></i> Analizar con IA
                        </button>
                    </div>

                    <div id="lib-analysis-result-container" style="margin-top: 12px; display: none;"></div>
                </div>

                <!-- Sección 2: Citas Técnicas Guardadas (<libreria>.json) -->
                <div style="background: var(--bg-panel); border: 1px solid var(--border-color); border-radius: 8px; padding: 16px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                        <div>
                            <h3 style="margin: 0; font-size: 14px; color: #fff; display: flex; align-items: center; gap: 6px;">
                                <i class="fa-solid fa-database" style="color: var(--accent-green);"></i> Citas y Recetas Técnicas Guardadas
                            </h3>
                            <span style="font-size: 11px; color: var(--text-muted); font-family: monospace;">Archivo: ${jsonFileName} (${citas.length} recetas para los modelos)</span>
                        </div>
                    </div>

                    <div style="display: flex; flex-direction: column; gap: 10px;">
                        ${citasListHtml}
                    </div>
                </div>

            </div>
        `;
    }

    async runLibraryAnalysis(libId) {
        const input = document.getElementById('input-lib-analyze-topic');
        const container = document.getElementById('lib-analysis-result-container');
        if (!input || !container) return;

        const topic = input.value.trim();
        if (!topic) {
            alert('Escribe el nombre de la función, clase o módulo a analizar.');
            return;
        }

        container.style.display = 'block';
        container.innerHTML = `<div style="padding: 20px; text-align: center; color: var(--text-muted);"><i class="fa-solid fa-spinner fa-spin fa-2x"></i><br><br>Analizando API de '${topic}' con el modelo de IA...</div>`;

        try {
            const model = (window.aiConfig && window.aiConfig.agent1_model) || 'qwen2.5-coder:7b';
            const res = await fetch('/api/librerias/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ lib_id: libId, topic: topic, model: model })
            });
            const data = await res.json();
            if (data.error) throw new Error(data.error);

            const a = data.analysis;
            container.innerHTML = `
                <div style="background: var(--bg-dark); border: 1px solid var(--accent-green); border-radius: 6px; padding: 14px; display: flex; flex-direction: column; gap: 10px;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-weight: bold; color: var(--accent-green); font-size: 14px;">
                            <i class="fa-solid fa-check-circle"></i> ${a.tema || topic}
                        </span>
                        <span style="font-size: 11px; color: var(--accent-blue); font-family: monospace;">${a.modulo || libId}</span>
                    </div>

                    <div style="font-size: 12px; color: var(--text-main); line-height: 1.5;">${a.explicacion || ''}</div>

                    <div style="background: #11111b; border: 1px solid var(--border-color); border-radius: 4px; padding: 10px;">
                        <pre style="margin: 0; font-family: 'Fira Code', monospace; font-size: 11px; color: #a6e3a1; overflow-x: auto; white-space: pre-wrap;">${a.snippet || ''}</pre>
                    </div>

                    ${a.parametros_clave && a.parametros_clave.length > 0 ? `
                        <div style="font-size: 11px; color: var(--accent-yellow);">
                            <strong>Parámetros clave:</strong> ${a.parametros_clave.join(', ')}
                        </div>
                    ` : ''}

                    <div style="display: flex; justify-content: flex-end; gap: 8px; margin-top: 6px;">
                        <button class="tool-btn" style="background: rgba(166,227,161,0.2); color: var(--accent-green); border-color: rgba(166,227,161,0.4); padding: 4px 12px;" onclick="window.bookLibraryMgr.saveLibraryCitation('${libId}', ${JSON.stringify(a).replace(/"/g, '&quot;')});">
                            <i class="fa-solid fa-floppy-disk"></i> Guardar como Cita en ${libId}.json
                        </button>
                    </div>
                </div>
            `;
        } catch (e) {
            container.innerHTML = `<div style="padding: 15px; color: var(--accent-red);"><i class="fa-solid fa-triangle-exclamation"></i> Error analizando: ${e.message}</div>`;
        }
    }

    async saveLibraryCitation(libId, citationData) {
        try {
            const res = await fetch('/api/librerias/citations/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    lib_id: libId,
                    citation: citationData
                })
            });
            const data = await res.json();
            if (data.error) throw new Error(data.error);

            alert(`¡Cita técnica guardada con éxito en ${data.archivo_json}!\nAhora cualquier modelo puede razonar con ella.`);
            await this.selectLibrary(libId);
        } catch (e) {
            alert(`Error guardando cita de librería: ${e.message}`);
        }
    }

    async deleteLibraryCitation(libId, citationId) {
        if (!confirm('¿Eliminar esta receta/cita de la librería?')) return;
        try {
            const res = await fetch('/api/librerias/citations/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    lib_id: libId,
                    citation_id: citationId
                })
            });
            const data = await res.json();
            if (data.error) throw new Error(data.error);
            await this.selectLibrary(libId);
        } catch (e) {
            alert(`Error eliminando cita: ${e.message}`);
        }
    }

    async exportLibraryCitations(libId) {
        try {
            const res = await fetch('/api/librerias/citations/export', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ lib_id: libId })
            });
            const data = await res.json();
            if (data.error) throw new Error(data.error);
            alert(`¡Archivo exportado con éxito!\n\nSe ha copiado '${data.filename}' (${data.total_citas} citas) a tu espacio de trabajo para consulta.`);
        } catch (e) {
            alert(`Error exportando: ${e.message}`);
        }
    }

    askChatWithLibraryCitation(cita, libName) {
        const promptText = `A partir de la siguiente referencia técnica de la librería "${libName || cita.modulo}":\n\n\`\`\`python\n${cita.snippet}\n\`\`\`\n\nExplicación: ${cita.explicacion}\n\n¿Cómo puedo adaptar o aplicar esta función en mi proyecto de Machine Learning / Data Science? Explícame sus parámetros y casos de uso avanzados.`;

        this.closeModal();
        if (window.app && window.app.sendAIChatMessage) {
            window.app.sendAIChatMessage(promptText, { selected_citations: [cita] });
        } else {
            const chatInput = document.getElementById('chat-input');
            if (chatInput) {
                chatInput.value = promptText;
                chatInput.focus();
            }
        }
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
                    page: this.currentPdfPage || 1,
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
