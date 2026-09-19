/**
 * Papers y Algoritmos Seminales de Machine Learning en Prig IDE
 * Visualizador interactivo de las 21 monografías, integración con GitHub,
 * descarga directa al proyecto y análisis con modelos de lenguaje.
 */

(function () {
    const $ = (id) => document.getElementById(id);
    const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

    class PapersMLManager {
        constructor() {
            this.papers = [];
            this.filtroCategoria = 'todas';
            this.busqueda = '';
            this.seleccionado = null;
            this.tipoDoc = 'analisis'; // 'analisis' (monografía exhaustiva) o 'ficha' (resumen técnico)
            this.contenido = null;
            this.cargandoDoc = false;
            this.cargandoLista = false;
            this.chatAbierto = true;
            this.chatMensajes = [];
            this.modelo = 'qwen2.5-coder:7b';
            this.modelosDisponibles = [];
            this.generandoRespuesta = false;
            this.iniciado = false;
        }

        async init() {
            this.inyectarEstilos();
            await this.cargarModelos();
            await this.cargarLista();
            if (!this.iniciado) {
                this.iniciado = true;
            }
        }

        inyectarEstilos() {
            if ($('papers-ml-estilos')) return;
            const style = document.createElement('style');
            style.id = 'papers-ml-estilos';
            style.textContent = `
                .pml-contenedor { display: grid; grid-template-columns: 320px 1fr 340px; height: 100%; min-height: 0; background: var(--bg-dark); gap: 10px; overflow: hidden; }
                .pml-contenedor.sin-chat { grid-template-columns: 340px 1fr; }
                .pml-panel { background: var(--bg-panel); border: 1px solid var(--border-color); border-radius: 8px; display: flex; flex-direction: column; overflow: hidden; min-height: 0; }
                .pml-header { padding: 10px 14px; border-bottom: 1px solid var(--border-color); display: flex; justify-content: space-between; align-items: center; background: rgba(0,0,0,0.15); flex-shrink: 0; }
                .pml-search { width: 100%; background: var(--bg-dark); border: 1px solid var(--border-color); border-radius: 6px; padding: 6px 10px; color: var(--text-main); font-size: 12px; outline: none; }
                .pml-search:focus { border-color: var(--accent-purple); }
                .pml-chips { display: flex; gap: 4px; overflow-x: auto; padding: 6px 0; scrollbar-width: none; }
                .pml-chip { font-size: 10.5px; padding: 3px 8px; border-radius: 12px; background: rgba(255,255,255,0.05); color: var(--text-muted); cursor: pointer; border: 1px solid transparent; white-space: nowrap; }
                .pml-chip:hover { background: rgba(255,255,255,0.1); color: #fff; }
                .pml-chip.activo { background: rgba(203,166,247,0.18); color: var(--accent-purple); border-color: rgba(203,166,247,0.4); font-weight: bold; }
                .pml-item { padding: 9px 12px; border-bottom: 1px solid rgba(255,255,255,0.04); cursor: pointer; display: flex; gap: 10px; align-items: flex-start; transition: background 0.15s; }
                .pml-item:hover { background: rgba(255,255,255,0.03); }
                .pml-item.seleccionado { background: rgba(203,166,247,0.1); border-left: 3px solid var(--accent-purple); }
                .pml-num { font-size: 11px; font-weight: bold; color: var(--text-muted); background: rgba(255,255,255,0.06); padding: 2px 6px; border-radius: 4px; flex-shrink: 0; }
                .pml-btn { font-size: 11.5px; padding: 5px 10px; border-radius: 6px; background: rgba(255,255,255,0.05); color: var(--text-main); border: 1px solid var(--border-color); cursor: pointer; display: inline-flex; align-items: center; gap: 6px; text-decoration: none; }
                .pml-btn:hover { background: rgba(255,255,255,0.1); border-color: var(--accent-blue); color: #fff; }
                .pml-btn.morado { background: rgba(203,166,247,0.15); border-color: rgba(203,166,247,0.4); color: var(--accent-purple); font-weight: 600; }
                .pml-btn.verde { background: rgba(166,227,161,0.15); border-color: rgba(166,227,161,0.4); color: var(--accent-green); }
                .pml-btn.activo { background: var(--accent-purple); color: #111; font-weight: bold; }
                .pml-doc-body { flex: 1; overflow-y: auto; padding: 24px 28px; line-height: 1.65; font-size: 13.5px; color: #cdd6f4; }
                .pml-doc-body pre { background: #181825; border: 1px solid var(--border-color); border-radius: 8px; padding: 12px; overflow-x: auto; font-size: 12px; }
                .pml-doc-body code { font-family: 'Fira Code', 'Consolas', monospace; }
                .pml-doc-body h1, .pml-doc-body h2, .pml-doc-body h3 { color: #fff; border-bottom: 1px solid rgba(255,255,255,0.08); padding-bottom: 6px; margin-top: 24px; }
                .pml-chat-msg { padding: 8px 12px; border-radius: 8px; margin-bottom: 8px; font-size: 12px; line-height: 1.5; word-break: break-word; }
                .pml-chat-user { background: rgba(137,180,250,0.12); border: 1px solid rgba(137,180,250,0.25); color: #89b4fa; margin-left: 14px; }
                .pml-chat-model { background: rgba(255,255,255,0.04); border: 1px solid var(--border-color); color: #cdd6f4; margin-right: 14px; }
                .pml-preguntas-sug { display: flex; flex-direction: column; gap: 4px; margin-top: 6px; }
                .pml-sug-item { font-size: 11px; padding: 5px 8px; border-radius: 6px; background: rgba(203,166,247,0.08); border: 1px solid rgba(203,166,247,0.2); color: var(--text-main); cursor: pointer; text-align: left; }
                .pml-sug-item:hover { background: rgba(203,166,247,0.2); color: #fff; }
            `;
            document.head.appendChild(style);
        }

        async cargarModelos() {
            try {
                const res = await window.prigFetchJson('/api/modelos/instalados');
                if (res && res.modelos && res.modelos.length) {
                    this.modelosDisponibles = res.modelos.map(m => m.name || m);
                    this.modelo = this.modelosDisponibles[0];
                }
            } catch (e) {
                this.modelosDisponibles = ['qwen2.5-coder:7b', 'llama3', 'mistral'];
            }
        }

        async cargarLista() {
            const raiz = $('papers-ml-raiz');
            if (!raiz) return;

            this.cargandoLista = true;
            try {
                let url = '/api/papers/list';
                const params = [];
                if (this.busqueda) params.push(`q=${encodeURIComponent(this.busqueda)}`);
                if (this.filtroCategoria && this.filtroCategoria !== 'todas') params.push(`categoria=${encodeURIComponent(this.filtroCategoria)}`);
                if (params.length) url += '?' + params.join('&');

                const data = await window.prigFetchJson(url);
                this.papers = data.papers || [];

                if (!this.seleccionado && this.papers.length) {
                    this.seleccionado = this.papers[0];
                } else if (this.seleccionado) {
                    // Mantener seleccionado si existe en los resultados
                    const existe = this.papers.find(p => p.id === this.seleccionado.id);
                    if (existe) this.seleccionado = existe;
                    else if (this.papers.length) this.seleccionado = this.papers[0];
                }
            } catch (e) {
                console.error('Error cargando papers:', e);
            } finally {
                this.cargandoLista = false;
                this.render();
                if (this.seleccionado) {
                    this.cargarDocumento(this.seleccionado.id);
                }
            }
        }

        async cargarDocumento(paperId) {
            this.cargandoDoc = true;
            this.renderDoc();
            try {
                const res = await window.prigFetchJson(`/api/papers/detail?id=${encodeURIComponent(paperId)}&tipo=${this.tipoDoc}`);
                if (res && res.contenido) {
                    this.contenido = res.contenido;
                } else {
                    this.contenido = 'No se pudo cargar el documento.';
                }
            } catch (e) {
                this.contenido = `Error al cargar documento: ${e.message}`;
            } finally {
                this.cargandoDoc = false;
                this.renderDoc();
            }
        }

        async descargarAlProyecto() {
            if (!this.seleccionado) return;
            const statusEl = $('pml-doc-status');
            if (statusEl) statusEl.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Guardando en workspace…';

            try {
                const res = await window.prigFetchJson('/api/papers/download', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ paper_id: this.seleccionado.id, tipo: this.tipoDoc })
                });

                if (res && res.ok) {
                    if (statusEl) {
                        statusEl.innerHTML = `<span style="color:var(--accent-green);"><i class="fa-solid fa-check"></i> ${esc(res.mensaje)}</span>`;
                        setTimeout(() => { if (statusEl) statusEl.innerHTML = ''; }, 4000);
                    }
                    if (window.fileTreeMgr) window.fileTreeMgr.loadTree();
                } else {
                    throw new Error(res.error || 'Error al guardar');
                }
            } catch (e) {
                if (statusEl) statusEl.innerHTML = `<span style="color:var(--accent-red);"><i class="fa-solid fa-triangle-exclamation"></i> ${esc(e.message)}</span>`;
            }
        }

        abrirEnGitHubLector() {
            if (window.GitHubLector) {
                window.GitHubLector.abrir({ ref: 'guillermopetcho/Prig-IDE' });
            } else {
                window.open('https://github.com/guillermopetcho/Prig-IDE/tree/main/docs', '_blank');
            }
        }

        buscarEnGitHub(query) {
            const q = query || (this.seleccionado ? this.seleccionado.titulo : 'machine learning papers');
            if (window.GitHubLector) {
                window.GitHubLector.abrir();
                const inp = document.getElementById('gh-q');
                if (inp) {
                    inp.value = q;
                    inp.dispatchEvent(new Event('input'));
                }
            } else {
                window.open(`https://github.com/search?q=${encodeURIComponent(q)}&type=repositories`, '_blank');
            }
        }

        async enviarPregunta(preguntaTexto) {
            const txt = (preguntaTexto || ($('pml-chat-input') ? $('pml-chat-input').value : '')).trim();
            if (!txt || this.generandoRespuesta || !this.seleccionado) return;

            if ($('pml-chat-input')) $('pml-chat-input').value = '';

            this.chatMensajes.push({ rol: 'user', texto: txt });
            const botMsg = { rol: 'model', texto: '' };
            this.chatMensajes.push(botMsg);
            this.renderChatMensajes();

            this.generandoRespuesta = true;
            const btnEnviar = $('pml-chat-send');
            if (btnEnviar) btnEnviar.disabled = true;

            try {
                const resp = await fetch('/api/papers/ask', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        paper_id: this.seleccionado.id,
                        pregunta: txt,
                        modelo: this.modelo,
                        tipo: this.tipoDoc,
                        historial: this.chatMensajes.slice(0, -2)
                    })
                });

                if (!resp.ok) throw new Error(`Error en servidor: ${resp.status}`);

                const reader = resp.body.getReader();
                const decoder = new TextDecoder('utf-8');

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    const chunk = decoder.decode(value, { stream: true });
                    botMsg.texto += chunk;
                    this.actualizarUltimoMensaje(botMsg.texto);
                }
            } catch (e) {
                botMsg.texto += `\n[Error al consultar con el modelo: ${e.message}]`;
                this.actualizarUltimoMensaje(botMsg.texto);
            } finally {
                this.generandoRespuesta = false;
                if (btnEnviar) btnEnviar.disabled = false;
            }
        }

        actualizarUltimoMensaje(texto) {
            const container = $('pml-chat-mensajes');
            if (!container) return;
            const last = container.lastElementChild;
            if (last && last.classList.contains('pml-chat-model')) {
                last.innerHTML = this.renderMarkdown(texto);
                container.scrollTop = container.scrollHeight;
            }
        }

        renderMarkdown(texto) {
            if (!texto) return '';
            let html = window.marked ? window.marked.parse(texto) : `<pre>${esc(texto)}</pre>`;
            if (window.DOMPurify) html = DOMPurify.sanitize(html);
            return html;
        }

        render() {
            const raiz = $('papers-ml-raiz');
            if (!raiz) return;

            raiz.innerHTML = `
                <div class="pml-contenedor ${this.chatAbierto ? '' : 'sin-chat'}">
                    <!-- Columna 1: Catálogo y Búsqueda -->
                    <div class="pml-panel">
                        <div class="pml-header">
                            <span style="font-weight:bold; font-size:13px; color:#fff; display:flex; align-items:center; gap:6px;">
                                <i class="fa-solid fa-graduation-cap" style="color:var(--accent-purple);"></i>
                                Papers Seminales (21)
                            </span>
                            <button class="pml-btn" onclick="window.papersML.abrirEnGitHubLector()" title="Ver repositorio completo en GitHub Lector">
                                <i class="fa-brands fa-github"></i> GitHub
                            </button>
                        </div>
                        <div style="padding:10px 12px; border-bottom:1px solid var(--border-color); display:flex; flex-direction:column; gap:8px;">
                            <input type="text" id="pml-search-input" class="pml-search" placeholder="🔍 Buscar paper, autor, RoPE, GOSS..." value="${esc(this.busqueda)}">
                            <div class="pml-chips">
                                <span class="pml-chip ${this.filtroCategoria === 'todas' ? 'activo' : ''}" onclick="window.papersML.setFiltro('todas')">Todos (21)</span>
                                <span class="pml-chip ${this.filtroCategoria === 'supervisado' ? 'activo' : ''}" onclick="window.papersML.setFiltro('supervisado')">Supervisado</span>
                                <span class="pml-chip ${this.filtroCategoria === 'ensembles' ? 'activo' : ''}" onclick="window.papersML.setFiltro('ensembles')">Ensembles</span>
                                <span class="pml-chip ${this.filtroCategoria === 'clustering' ? 'activo' : ''}" onclick="window.papersML.setFiltro('clustering')">Clustering</span>
                                <span class="pml-chip ${this.filtroCategoria === 'deep learning' ? 'activo' : ''}" onclick="window.papersML.setFiltro('deep learning')">Deep Learning</span>
                                <span class="pml-chip ${this.filtroCategoria === 'generativo' ? 'activo' : ''}" onclick="window.papersML.setFiltro('generativo')">Generativo</span>
                            </div>
                        </div>
                        <div id="pml-lista-items" style="flex:1; overflow-y:auto;">
                            ${this.renderListaItems()}
                        </div>
                    </div>

                    <!-- Columna 2: Visor del Paper / Ficha -->
                    <div class="pml-panel">
                        <div class="pml-header" style="background:rgba(0,0,0,0.25);">
                            <div style="display:flex; align-items:center; gap:8px; min-width:0;">
                                <div style="display:flex; gap:4px; background:rgba(0,0,0,0.3); padding:2px; border-radius:6px;">
                                    <button class="pml-btn ${this.tipoDoc === 'analisis' ? 'activo' : ''}" onclick="window.papersML.setTipoDoc('analisis')" title="Monografía doctoral exhaustiva con derivaciones paso a paso">
                                        <i class="fa-solid fa-book"></i> Monografía Doctoral
                                    </button>
                                    <button class="pml-btn ${this.tipoDoc === 'ficha' ? 'activo' : ''}" onclick="window.papersML.setTipoDoc('ficha')" title="Ficha técnica concisa con diagramas modulares">
                                        <i class="fa-solid fa-list-check"></i> Ficha Técnica
                                    </button>
                                </div>
                                <span id="pml-doc-status" style="font-size:11.5px; margin-left:6px;"></span>
                            </div>
                            <div style="display:flex; gap:6px; align-items:center;">
                                <button class="pml-btn verde" onclick="window.papersML.descargarAlProyecto()" title="Descargar este archivo Markdown al proyecto local (papers_ml/)">
                                    <i class="fa-solid fa-download"></i> Guardar en Proyecto
                                </button>
                                <a class="pml-btn" id="pml-btn-gh-externo" href="${this.seleccionado ? this.seleccionado.github_url_analisis : '#'}" target="_blank" rel="noopener noreferrer" title="Ver en GitHub">
                                    <i class="fa-brands fa-github"></i>
                                </a>
                                <button class="pml-btn ${this.chatAbierto ? 'morado' : ''}" onclick="window.papersML.toggleChat()" title="Alternar panel de análisis con modelo">
                                    <i class="fa-solid fa-robot"></i> ${this.chatAbierto ? 'Ocultar Tutor' : 'Preguntar al Modelo'}
                                </button>
                            </div>
                        </div>
                        <div id="pml-doc-viewer" class="pml-doc-body">
                            <!-- Renderizado del documento -->
                        </div>
                    </div>

                    <!-- Columna 3: Chat / Tutor de IA -->
                    ${this.chatAbierto ? `
                    <div class="pml-panel">
                        <div class="pml-header" style="background:rgba(203,166,247,0.06);">
                            <span style="font-weight:bold; font-size:12.5px; color:var(--accent-purple); display:flex; align-items:center; gap:6px;">
                                <i class="fa-solid fa-robot"></i> Tutor de Papers
                            </span>
                            <select id="pml-model-select" style="background:#181825; border:1px solid var(--accent-purple); color:var(--accent-purple); border-radius:4px; padding:2px 6px; font-size:11px; cursor:pointer;" onchange="window.papersML.modelo = this.value">
                                ${this.modelosDisponibles.map(m => `<option value="${esc(m)}" ${m === this.modelo ? 'selected' : ''}>${esc(m)}</option>`).join('')}
                            </select>
                        </div>
                        <div style="padding:8px 12px; background:rgba(0,0,0,0.2); border-bottom:1px solid var(--border-color);">
                            <div style="font-size:10.5px; color:var(--text-muted); margin-bottom:4px;">PREGUNTAS SUGERIDAS:</div>
                            <div class="pml-preguntas-sug">
                                <div class="pml-sug-item" onclick="window.papersML.enviarPregunta('¿Cómo se deduce la función de pérdida paso a paso?')">📐 Deducir función de pérdida</div>
                                <div class="pml-sug-item" onclick="window.papersML.enviarPregunta('¿Cuál es la intuición geométrica y los teoremas clave de este paper?')">🔍 Teoremas clave e intuición</div>
                                <div class="pml-sug-item" onclick="window.papersML.enviarPregunta('Explica la implementación de referencia en NumPy puro.')">💻 Explicar código NumPy</div>
                                <div class="pml-sug-item" onclick="window.papersML.enviarPregunta('¿Cuáles son los hiperparámetros críticos y modos de falla?')">⚠️ Hiperparámetros y fallas</div>
                            </div>
                        </div>
                        <div id="pml-chat-mensajes" style="flex:1; overflow-y:auto; padding:12px; display:flex; flex-direction:column;">
                            <!-- Mensajes de chat -->
                        </div>
                        <div style="padding:10px; border-top:1px solid var(--border-color); display:flex; gap:6px; background:rgba(0,0,0,0.2);">
                            <input type="text" id="pml-chat-input" class="pml-search" placeholder="Pregunta sobre este paper..." onkeydown="if(event.key==='Enter') window.papersML.enviarPregunta();">
                            <button id="pml-chat-send" class="pml-btn morado" onclick="window.papersML.enviarPregunta()" title="Enviar pregunta">
                                <i class="fa-solid fa-paper-plane"></i>
                            </button>
                        </div>
                    </div>
                    ` : ''}
                </div>
            `;

            // Bind de búsqueda con debounce
            const searchInp = $('pml-search-input');
            if (searchInp) {
                searchInp.oninput = (e) => {
                    this.busqueda = e.target.value;
                    clearTimeout(this._timerBusqueda);
                    this._timerBusqueda = setTimeout(() => this.cargarLista(), 250);
                };
            }

            this.renderDoc();
            this.renderChatMensajes();
        }

        renderListaItems() {
            if (this.cargandoLista) {
                return '<div style="padding:20px; text-align:center; color:var(--text-muted); font-size:12px;"><i class="fa-solid fa-spinner fa-spin"></i> Buscando papers…</div>';
            }
            if (!this.papers.length) {
                return '<div style="padding:20px; text-align:center; color:var(--text-muted); font-size:12px;">No se encontraron algoritmos coincidentes.</div>';
            }

            return this.papers.map(p => {
                const esActivo = this.seleccionado && this.seleccionado.id === p.id;
                const kb = Math.round(p.analisis_bytes / 1024);
                return `
                    <div class="pml-item ${esActivo ? 'seleccionado' : ''}" onclick="window.papersML.seleccionarPaper('${p.id}')">
                        <span class="pml-num">${p.num.toString().padStart(2, '0')}</span>
                        <div style="min-width:0; flex:1;">
                            <div style="font-weight:600; font-size:12.5px; color:${esActivo ? 'var(--accent-purple)' : '#fff'}; line-height:1.3; margin-bottom:3px;">
                                ${esc(p.titulo)}
                            </div>
                            <div style="font-size:11px; color:var(--text-muted); display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
                                <span style="color:${p.color}; font-size:10px;"><i class="fa-solid ${p.icono}"></i> ${esc(p.categoria)}</span>
                                <span>·</span>
                                <span>${kb} KB</span>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
        }

        renderDoc() {
            const viewer = $('pml-doc-viewer');
            if (!viewer) return;

            if (this.cargandoDoc) {
                viewer.innerHTML = '<div style="padding:40px; text-align:center; color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin fa-2x"></i><p style="margin-top:12px; font-size:13px;">Cargando documento científico…</p></div>';
                return;
            }

            if (!this.contenido) {
                viewer.innerHTML = '<div style="padding:40px; text-align:center; color:var(--text-muted);">Selecciona un paper para inspeccionar su formulación matemática y derivaciones.</div>';
                return;
            }

            viewer.innerHTML = this.renderMarkdown(this.contenido);

            // Resaltado de código si hljs existe
            if (window.hljs) {
                viewer.querySelectorAll('pre code').forEach(block => {
                    try { hljs.highlightElement(block); } catch (e) {}
                });
            }
        }

        renderChatMensajes() {
            const container = $('pml-chat-mensajes');
            if (!container) return;

            if (!this.chatMensajes.length) {
                container.innerHTML = `
                    <div style="padding:20px 10px; text-align:center; color:var(--text-muted); font-size:11.5px;">
                        <i class="fa-solid fa-comments" style="font-size:28px; margin-bottom:10px; opacity:0.6; color:var(--accent-purple);"></i>
                        <p>Haz preguntas sobre este paper seminal al modelo de lenguaje. El modelo analizará las derivaciones, ecuaciones y la implementación en NumPy puro.</p>
                    </div>
                `;
                return;
            }

            container.innerHTML = this.chatMensajes.map(m => {
                const esUser = m.rol === 'user';
                return `
                    <div class="pml-chat-msg ${esUser ? 'pml-chat-user' : 'pml-chat-model'}">
                        <div style="font-size:10px; font-weight:bold; margin-bottom:3px; opacity:0.8;">
                            ${esUser ? '<i class="fa-solid fa-user"></i> Tú' : '<i class="fa-solid fa-robot"></i> Tutor (' + esc(this.modelo) + ')'}
                        </div>
                        <div>${this.renderMarkdown(m.texto)}</div>
                    </div>
                `;
            }).join('');

            container.scrollTop = container.scrollHeight;
        }

        seleccionarPaper(paperId) {
            const p = this.papers.find(x => x.id === paperId);
            if (p) {
                this.seleccionado = p;
                this.chatMensajes = []; // Reiniciar conversación para el nuevo paper
                this.cargarDocumento(paperId);
                const itemsContainer = $('pml-lista-items');
                if (itemsContainer) itemsContainer.innerHTML = this.renderListaItems();
                const ghBtn = $('pml-btn-gh-externo');
                if (ghBtn) ghBtn.href = p.github_url_analisis;
            }
        }

        setFiltro(cat) {
            this.filtroCategoria = cat;
            this.cargarLista();
        }

        setTipoDoc(tipo) {
            if (this.tipoDoc !== tipo) {
                this.tipoDoc = tipo;
                if (this.seleccionado) this.cargarDocumento(this.seleccionado.id);
                this.render();
            }
        }

        toggleChat() {
            this.chatAbierto = !this.chatAbierto;
            this.render();
        }
    }

    window.papersML = new PapersMLManager();
})();
