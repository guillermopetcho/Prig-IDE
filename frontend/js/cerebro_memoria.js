/**
 * ============================================================================
 * CEREBRO IA · GESTOR DE MEMORIA COMPRIMIDA Y CONSULTAS SEMÁNTICAS (PRIG IDE)
 * ============================================================================
 * - Controla el panel lateral derecho del Cerebro IA.
 * - Gestiona el historial de razonamientos y diálogos del modelo.
 * - Muestra la memoria estructurada de archivos leídos (firmas AST, símbolos, dependencias)
 *   ahorrando entre un 85% y 92% de tokens.
 * - Permite al usuario chatear y hacer preguntas técnicas sobre todo lo que el modelo ha leído.
 */

(function(root) {
    'use strict';

    class CerebroMemoriaManager {
        constructor() {
            this.panelEl = null;
            this.tabActiva = 'dialogos'; // 'dialogos' | 'memoria' | 'preguntar'
            this.archivosMemorizados = [];
            this.statsTokens = {};
            this.historialDialogos = [];
            this.historialChat = [];
            this.consultando = false;
            this.modelo = 'qwen2.5-coder:7b';
            this.endpoint = 'http://localhost:11434';
            this._iniciado = false;
        }

        init() {
            if (this._iniciado) return;
            this._iniciado = true;

            this.panelEl = document.getElementById('panel-cerebro-memoria');
            this._vincularEventosTeclado();
            this.actualizarMemoria();

            // Sincronizar periódicamente cada 15 segundos
            setInterval(() => {
                if (this.panelEl && this.panelEl.classList.contains('abierto')) {
                    this.actualizarMemoria(false);
                } else {
                    this._actualizarBadgeContador();
                }
            }, 15000);
        }

        _vincularEventosTeclado() {
            window.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && this.estaAbierto()) {
                    this.cerrarPanel();
                }
            });
        }

        estaAbierto() {
            return this.panelEl && this.panelEl.classList.contains('abierto');
        }

        alternarPanel() {
            if (this.estaAbierto()) {
                this.cerrarPanel();
            } else {
                this.abrirPanel();
            }
        }

        abrirPanel(tabDeseada = null) {
            if (!this.panelEl) this.panelEl = document.getElementById('panel-cerebro-memoria');
            if (!this.panelEl) return;

            this.panelEl.classList.add('abierto');
            if (tabDeseada) this.setTab(tabDeseada);
            this.actualizarMemoria(true);
        }

        cerrarPanel() {
            if (this.panelEl) {
                this.panelEl.classList.remove('abierto');
            }
        }

        setTab(tabId) {
            this.tabActiva = tabId;
            document.querySelectorAll('.cerebro-tab-btn').forEach(btn => {
                btn.classList.toggle('activa', btn.dataset.tab === tabId);
            });
            document.querySelectorAll('.cerebro-tab-content').forEach(view => {
                view.style.display = (view.id === `cerebro-tab-${tabId}`) ? 'flex' : 'none';
            });

            if (tabId === 'preguntar') {
                const input = document.getElementById('cerebro-chat-input');
                if (input) setTimeout(() => input.focus(), 100);
            }
        }

        async actualizarMemoria(mostrarLoader = false) {
            try {
                const resp = await fetch('/api/llm/memoria_archivos');
                if (resp.ok) {
                    const data = await resp.json();
                    if (data.ok) {
                        this.archivosMemorizados = data.archivos || [];
                        this.statsTokens = data.stats || {};
                        this._renderizarMemoria();
                        this._renderizarStatsHero();
                        this._actualizarBadgeContador();
                    }
                }
            } catch (err) {
                console.debug('No se pudo sincronizar memoria del cerebro:', err);
            }

            this.cargarHistorialDialogos();
        }

        _actualizarBadgeContador() {
            const badge = document.getElementById('badge-cerebro-memoria');
            if (!badge) return;

            const count = this.archivosMemorizados.length;
            if (count > 0) {
                badge.innerText = `${count} ${count === 1 ? 'archivo leído' : 'archivos leídos'}`;
                badge.style.display = 'inline-block';
            } else {
                badge.innerText = '0 leídos';
            }
        }

        _renderizarStatsHero() {
            const heroEl = document.getElementById('cerebro-stats-hero');
            if (!heroEl) return;

            const totalCrudo = this.statsTokens.total_tokens_crudos_evitados || 0;
            const totalComp = this.statsTokens.total_tokens_comprimidos_usados || 0;
            const ahorro = this.statsTokens.ahorro_global_porcentaje || 0;
            const netos = this.statsTokens.tokens_netos_ahorrados || 0;

            heroEl.innerHTML = `
                <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px;">
                    <div>
                        <div style="font-size: 11px; color: #a6adc8; text-transform: uppercase; font-weight: 700; letter-spacing: 0.5px;">
                            <i class="fa-solid fa-bolt" style="color: #f9e2af;"></i> EFICIENCIA DE TOKENS (TC-AST)
                        </div>
                        <div style="font-size: 14px; font-weight: 800; color: #a6e3a1; margin-top: 2px;">
                            ${ahorro}% Ahorro Semántico
                        </div>
                    </div>
                    <div style="text-align: right; font-size: 11px; color: #cdd6f4; font-family: 'Fira Code', monospace;">
                        <span style="color: #f38ba8; text-decoration: line-through;">${totalCrudo.toLocaleString()} raw</span><br>
                        <span style="color: #89b4fa; font-weight: 700;">${totalComp.toLocaleString()} comp</span>
                        <span style="color: #a6e3a1;">(↓ ${netos.toLocaleString()})</span>
                    </div>
                </div>
            `;
        }

        _renderizarMemoria() {
            const listaEl = document.getElementById('cerebro-lista-archivos-memoria');
            if (!listaEl) return;

            if (this.archivosMemorizados.length === 0) {
                listaEl.innerHTML = `
                    <div style="padding: 30px 16px; text-align: center; color: #6c7086;">
                        <i class="fa-solid fa-brain" style="font-size: 28px; opacity: 0.3; margin-bottom: 8px;"></i>
                        <p style="margin: 0; font-size: 12px;">Aún no se han indexado archivos.</p>
                        <span style="font-size: 11px; opacity: 0.7;">Abre o edita código para que el modelo genere sus firmas semánticas.</span>
                    </div>
                `;
                return;
            }

            let html = '';
            this.archivosMemorizados.forEach(item => {
                const simbolosCount = item.simbolos ? item.simbolos.length : 0;
                const depsCount = item.dependencias ? item.dependencias.length : 0;
                const criticos = item.puntos_criticos || [];
                const evalInfo = item.ultima_evaluacion || {};

                html += `
                    <div class="cerebro-card-archivo" style="background: rgba(30, 30, 46, 0.75); border: 1px solid rgba(137, 180, 250, 0.25); border-radius: 8px; padding: 12px; margin-bottom: 10px;">
                        <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; margin-bottom: 6px;">
                            <div style="display: flex; align-items: center; gap: 6px;">
                                <i class="fa-solid fa-file-code" style="color: #89dceb; font-size: 13px;"></i>
                                <span style="font-weight: 700; color: #f8fafc; font-size: 12px; font-family: 'Fira Code', monospace;">${item.archivo}</span>
                            </div>
                            <span style="background: rgba(166, 227, 161, 0.15); color: #a6e3a1; font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 4px; border: 1px solid rgba(166, 227, 161, 0.3);">
                                ↓ ${item.ahorro_tokens_pct || 90}% tokens
                            </span>
                        </div>

                        <div style="display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 8px;">
                            <span class="cerebro-chip-ast" style="background: rgba(203, 166, 247, 0.15); color: #cba6f7; font-size: 10px; padding: 2px 6px; border-radius: 4px;">
                                <i class="fa-solid fa-cube"></i> ${simbolosCount} Símbolos
                            </span>
                            <span class="cerebro-chip-ast" style="background: rgba(137, 180, 250, 0.15); color: #89b4fa; font-size: 10px; padding: 2px 6px; border-radius: 4px;">
                                <i class="fa-solid fa-network-wired"></i> ${depsCount} Deps
                            </span>
                            <span class="cerebro-chip-ast" style="background: rgba(249, 226, 175, 0.15); color: #f9e2af; font-size: 10px; padding: 2px 6px; border-radius: 4px;">
                                <i class="fa-solid fa-lines-leaning"></i> ${item.lineas_total} Líneas
                            </span>
                        </div>

                        ${criticos.length > 0 ? `
                            <div style="font-size: 10.5px; color: #fab387; margin-bottom: 6px; font-family: 'Fira Code', monospace;">
                                ⚠️ Puntos clave: ${criticos.slice(0, 2).join(' • ')}
                            </div>
                        ` : ''}

                        ${evalInfo.consejo_titulo ? `
                            <div style="font-size: 11px; color: #a6adc8; border-top: 1px dashed rgba(255,255,255,0.08); padding-top: 6px; margin-top: 4px;">
                                💡 <b style="color: #cdd6f4;">Última sugerencia:</b> ${evalInfo.consejo_titulo}
                            </div>
                        ` : ''}

                        <div style="display: flex; justify-content: flex-end; margin-top: 8px;">
                            <button onclick="window.CerebroMemoria.preguntarSobreArchivo('${item.archivo}')" style="background: rgba(137, 180, 250, 0.15); border: 1px solid #89b4fa; color: #89b4fa; border-radius: 4px; padding: 3px 8px; font-size: 11px; font-weight: 600; cursor: pointer;">
                                <i class="fa-solid fa-message"></i> Preguntar sobre este archivo
                            </button>
                        </div>
                    </div>
                `;
            });

            listaEl.innerHTML = html;
        }

        async cargarHistorialDialogos() {
            const container = document.getElementById('cerebro-lista-dialogos');
            if (!container) return;

            let historial = [];
            if (window.DIRECTOR_ASCII && window.DIRECTOR_ASCII.historialReciente) {
                historial = [...window.DIRECTOR_ASCII.historialReciente];
            }

            if (historial.length === 0) {
                container.innerHTML = `
                    <div style="padding: 30px 16px; text-align: center; color: #6c7086;">
                        <i class="fa-regular fa-comments" style="font-size: 28px; opacity: 0.3; margin-bottom: 8px;"></i>
                        <p style="margin: 0; font-size: 12px;">Sin evaluaciones registradas aún.</p>
                        <span style="font-size: 11px; opacity: 0.7;">El modelo emitirá razonamientos automáticos al inspeccionar código.</span>
                    </div>
                `;
                return;
            }

            let html = '';
            historial.slice().reverse().forEach((item, idx) => {
                const dec = item.decision || item;
                const personaje = dec.personaje || 'Evaluador IA';
                const dialogo = dec.dialogo || dec.pensamiento || 'Sin diálogo';
                const consejo = dec.consejo || {};
                const metricas = dec.metricas || {};

                html += `
                    <div class="cerebro-dialogo-card" style="background: rgba(24, 24, 37, 0.85); border: 1px solid rgba(203, 166, 247, 0.25); border-radius: 8px; padding: 12px; margin-bottom: 10px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                            <span style="font-size: 11.5px; font-weight: 800; color: #cba6f7;">
                                🧠 [${personaje}]
                            </span>
                            <span style="font-size: 10px; color: #a6adc8; font-family: 'Fira Code', monospace;">
                                COMPL: ${metricas.complejidad || 'O(N)'} | CAL: ${metricas.calidad || 96}%
                            </span>
                        </div>

                        <div style="font-size: 11.5px; color: #f8fafc; line-height: 1.45; margin-bottom: 8px;">
                            ${dialogo}
                        </div>

                        ${consejo.titulo ? `
                            <div style="background: rgba(17, 17, 27, 0.85); border-left: 3px solid #89dceb; padding: 6px 8px; border-radius: 4px; font-size: 11px;">
                                <div style="color: #89dceb; font-weight: 700;">📌 ${consejo.titulo}</div>
                                <div style="color: #a6adc8; margin-top: 2px;">${consejo.detalle || ''}</div>
                            </div>
                        ` : ''}
                    </div>
                `;
            });

            container.innerHTML = html;
        }

        preguntarSobreArchivo(nombreArchivo) {
            this.setTab('preguntar');
            const input = document.getElementById('cerebro-chat-input');
            if (input) {
                input.value = `¿Qué funciones, dependencias y mejoras identificaste en ${nombreArchivo}?`;
                input.focus();
            }
        }

        enviarPromptRapido(textoPrompt) {
            const input = document.getElementById('cerebro-chat-input');
            if (input) {
                input.value = textoPrompt;
                this.enviarPregunta();
            }
        }

        async enviarPregunta() {
            if (this.consultando) return;
            const input = document.getElementById('cerebro-chat-input');
            if (!input) return;

            const pregunta = input.value.trim();
            if (!pregunta) return;

            input.value = '';
            this.consultando = true;

            const chatContainer = document.getElementById('cerebro-chat-mensajes');
            if (chatContainer) {
                chatContainer.innerHTML += `
                    <div style="display: flex; justify-content: flex-end; margin-bottom: 10px;">
                        <div style="background: rgba(137, 180, 250, 0.22); border: 1px solid #89b4fa; color: #ffffff; padding: 8px 12px; border-radius: 8px; max-width: 85%; font-size: 12px;">
                            ${pregunta}
                        </div>
                    </div>
                    <div id="cerebro-chat-loading" style="display: flex; gap: 8px; align-items: center; margin-bottom: 10px; color: #cba6f7; font-size: 11px;">
                        <i class="fa-solid fa-spinner fa-spin"></i> Consultando memoria comprimida...
                    </div>
                `;
                chatContainer.scrollTop = chatContainer.scrollHeight;
            }

            try {
                const resp = await fetch('/api/llm/preguntar_cerebro', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        pregunta: pregunta,
                        modelo: this.modelo,
                        endpoint: this.endpoint
                    })
                });

                const loader = document.getElementById('cerebro-chat-loading');
                if (loader) loader.remove();

                if (resp.ok) {
                    const data = await resp.json();
                    if (data.ok && chatContainer) {
                        chatContainer.innerHTML += `
                            <div style="display: flex; justify-content: flex-start; margin-bottom: 12px;">
                                <div style="background: rgba(24, 24, 37, 0.92); border: 1px solid rgba(203, 166, 247, 0.4); color: #cdd6f4; padding: 10px 14px; border-radius: 8px; max-width: 90%; font-size: 12px; line-height: 1.45;">
                                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px;">
                                        <span style="font-weight: 700; color: #cba6f7; font-size: 11px;">
                                            🧠 CEREBRO IA
                                        </span>
                                        <span style="font-size: 10px; color: #a6e3a1; font-family: 'Fira Code', monospace;">
                                            ⚡ Ahorro: ${data.ahorro_porcentaje || 90}%
                                        </span>
                                    </div>
                                    <div>${data.respuesta}</div>
                                </div>
                            </div>
                        `;
                        chatContainer.scrollTop = chatContainer.scrollHeight;
                    }
                }
            } catch (err) {
                console.error('Error enviando pregunta al cerebro:', err);
                const loader = document.getElementById('cerebro-chat-loading');
                if (loader) loader.remove();
            } finally {
                this.consultando = false;
            }
        }

        async limpiarMemoria() {
            if (!confirm('¿Deseas reiniciar la memoria del Cerebro IA? Se vaciarán las firmas de archivos leídos.')) return;
            try {
                const resp = await fetch('/api/llm/limpiar_memoria_cerebro', { method: 'POST' });
                if (resp.ok) {
                    this.archivosMemorizados = [];
                    this.statsTokens = {};
                    this.actualizarMemoria();
                }
            } catch (err) {
                console.error('Error limpiando memoria:', err);
            }
        }
    }

    /**
     * ============================================================================
     * MODO CEREBRO FONDO (CTRL + ALT)
     * ============================================================================
     * Despeja el fondo del editor haciéndolo translúcido, centra el diálogo
     * de razonamiento del personaje en el medio de la pantalla y abre el Cerebro IA.
     * El personaje ASCII permanece anclado en la parte inferior derecha.
     */
    class ModoCerebroFondoManager {
        constructor() {
            this.activo = false;
            this.teclasPresionadas = { ctrl: false, alt: false };
            this._ultimoToggle = 0;
            this.init();
        }

        init() {
            this.inyectarEstilos();
            this.registrarAtajos();
        }

        inyectarEstilos() {
            if (document.getElementById('prig-modo-cerebro-fondo-css')) return;
            const style = document.createElement('style');
            style.id = 'prig-modo-cerebro-fondo-css';
            style.textContent = `
                /* Ocultar interfaz estándar en Modo Fondo Inmersivo */
                body.prig-modo-fondo-activo #workarea-container,
                body.prig-modo-fondo-activo #main-content-area,
                body.prig-modo-fondo-activo .editor-pane,
                body.prig-modo-fondo-activo .monaco-editor,
                body.prig-modo-fondo-activo #left-sidebar,
                body.prig-modo-fondo-activo #bottom-panel,
                body.prig-modo-fondo-activo .ide-top-bar,
                body.prig-modo-fondo-activo #statusbar,
                body.prig-modo-fondo-activo #notebook-view-container {
                    opacity: 0 !important;
                    transform: scale(0.96) !important;
                    pointer-events: none !important;
                    visibility: hidden !important;
                    transition: opacity 0.28s cubic-bezier(0.16, 1, 0.3, 1), transform 0.28s !important;
                }

                /* Fondo y Canvas 100% nítidos en pantalla completa */
                body.prig-modo-fondo-activo #matrix-artillery-canvas {
                    opacity: 1 !important;
                    filter: none !important;
                    z-index: 10 !important;
                }

                /* 1. MINIMAPA DE CÓDIGO (COLUMNA IZQUIERDA 20%) */
                #prig-minimapa-codigo-flotante {
                    position: fixed;
                    top: 5vh;
                    left: 1.5vw;
                    width: 18.5vw;
                    height: 90vh;
                    background: rgba(14, 17, 28, 0.42);
                    backdrop-filter: blur(9px);
                    -webkit-backdrop-filter: blur(9px);
                    border: 1px solid rgba(137, 180, 250, 0.28);
                    border-radius: 12px;
                    box-shadow: 0 16px 40px rgba(0, 0, 0, 0.5), 0 0 25px rgba(137, 180, 250, 0.15);
                    z-index: 999999;
                    display: flex;
                    flex-direction: column;
                    overflow: hidden;
                    cursor: pointer;
                    opacity: 0;
                    transform: translateX(-30px);
                    pointer-events: none;
                    transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
                    user-select: none;
                }

                #prig-minimapa-codigo-flotante.visible {
                    opacity: 1;
                    transform: translateX(0);
                    pointer-events: auto;
                }

                #prig-minimapa-codigo-flotante:hover {
                    border-color: #89b4fa;
                    background: rgba(18, 22, 36, 0.55);
                    box-shadow: 0 20px 48px rgba(0, 0, 0, 0.7), 0 0 35px rgba(137, 180, 250, 0.3);
                }

                .pmc-header {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    padding: 10px 14px;
                    background: rgba(24, 24, 37, 0.50);
                    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
                    font-size: 11px;
                    font-weight: 700;
                    color: #89b4fa;
                    font-family: 'Fira Code', monospace;
                }

                .pmc-badge {
                    background: rgba(137, 180, 250, 0.2);
                    color: #89b4fa;
                    padding: 2px 6px;
                    border-radius: 4px;
                    font-size: 9.5px;
                }

                .pmc-preview {
                    flex: 1;
                    padding: 12px 14px;
                    font-family: 'Fira Code', monospace;
                    font-size: 9.5px;
                    line-height: 1.45;
                    color: #a6adc8;
                    overflow: hidden;
                    background: transparent;
                    position: relative;
                }

                .pmc-preview-overlay {
                    position: absolute;
                    inset: 0;
                    background: linear-gradient(to bottom, transparent 65%, rgba(15, 17, 26, 0.85) 100%);
                    display: flex;
                    align-items: flex-end;
                    justify-content: center;
                    padding-bottom: 12px;
                    color: #89b4fa;
                    font-weight: 600;
                    font-size: 10.5px;
                }

                /* 2. CUADRO DE DIÁLOGO Y RAZONAMIENTO CENTRAL (COLUMNA CENTRAL 60%) */
                #prig-dialogo-central-modelo {
                    position: fixed;
                    top: 5vh;
                    left: 21vw;
                    width: 58vw;
                    height: 90vh;
                    background: rgba(14, 17, 28, 0.45);
                    backdrop-filter: blur(10px);
                    -webkit-backdrop-filter: blur(10px);
                    border: 1px solid rgba(203, 166, 247, 0.35);
                    border-radius: 14px;
                    box-shadow: 0 24px 60px rgba(0, 0, 0, 0.6), 0 0 35px rgba(203, 166, 247, 0.18);
                    z-index: 999998;
                    display: flex;
                    flex-direction: column;
                    overflow: hidden;
                    opacity: 0;
                    transform: scale(0.96);
                    pointer-events: none;
                    transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                    color: #cdd6f4;
                }

                #prig-dialogo-central-modelo.visible {
                    opacity: 1;
                    transform: scale(1);
                    pointer-events: auto;
                }

                /* 3. DOCK SUPERIOR DERECHO (COLUMNA DERECHA 20%) */
                #prig-dock-derecho-superior {
                    position: fixed;
                    top: 5vh;
                    right: 1.5vw;
                    width: 17.5vw;
                    max-height: 38vh;
                    background: rgba(14, 17, 28, 0.42);
                    backdrop-filter: blur(9px);
                    -webkit-backdrop-filter: blur(9px);
                    border: 1px solid rgba(203, 166, 247, 0.28);
                    border-radius: 12px;
                    box-shadow: 0 16px 40px rgba(0, 0, 0, 0.5);
                    z-index: 999997;
                    display: flex;
                    flex-direction: column;
                    padding: 12px 14px;
                    opacity: 0;
                    transform: translateX(30px);
                    pointer-events: none;
                    transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
                    font-family: 'Fira Code', monospace;
                    color: #cdd6f4;
                }

                #prig-dock-derecho-superior.visible {
                    opacity: 1;
                    transform: translateX(0);
                    pointer-events: auto;
                }

                .pdc-header {
                    padding: 12px 18px;
                    background: rgba(24, 24, 37, 0.50);
                    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                }

                .pdc-tabs {
                    display: flex;
                    gap: 6px;
                    padding: 8px 16px;
                    background: rgba(17, 17, 27, 0.40);
                    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
                    overflow-x: auto;
                }

                .pdc-tab-btn {
                    background: transparent;
                    border: 1px solid transparent;
                    color: #a6adc8;
                    font-size: 11px;
                    font-weight: 600;
                    padding: 5px 12px;
                    border-radius: 6px;
                    cursor: pointer;
                    transition: all 0.15s;
                    white-space: nowrap;
                }
                .pdc-tab-btn:hover {
                    color: #fff;
                    background: rgba(255, 255, 255, 0.08);
                }
                .pdc-tab-btn.activo {
                    background: rgba(203, 166, 247, 0.25);
                    border-color: rgba(203, 166, 247, 0.5);
                    color: #cba6f7;
                }

                .pdc-body {
                    flex: 1;
                    overflow-y: auto;
                    padding: 16px 20px;
                    display: flex;
                    flex-direction: column;
                    gap: 12px;
                    background: transparent;
                }

                .pdc-body::-webkit-scrollbar {
                    width: 5px;
                }
                .pdc-body::-webkit-scrollbar-thumb {
                    background: rgba(255, 255, 255, 0.15);
                    border-radius: 4px;
                }

                .pdc-chat-msg {
                    padding: 12px 16px;
                    border-radius: 8px;
                    font-size: 12.5px;
                    line-height: 1.55;
                }
                .pdc-chat-msg.modelo {
                    background: rgba(24, 24, 37, 0.65);
                    border: 1px solid rgba(203, 166, 247, 0.3);
                    color: #f8fafc;
                    font-family: 'Fira Code', monospace;
                }
                .pdc-chat-msg.usuario {
                    background: rgba(137, 180, 250, 0.25);
                    border: 1px solid rgba(137, 180, 250, 0.4);
                    color: #89b4fa;
                    align-self: flex-end;
                    max-width: 85%;
                }

                .pdc-chips {
                    display: flex;
                    gap: 8px;
                    padding: 8px 16px;
                    background: rgba(10, 12, 20, 0.35);
                    border-top: 1px solid rgba(255, 255, 255, 0.05);
                    overflow-x: auto;
                }

                .pdc-chip-btn {
                    background: rgba(137, 180, 250, 0.12);
                    border: 1px solid rgba(137, 180, 250, 0.3);
                    color: #89b4fa;
                    border-radius: 12px;
                    padding: 4px 10px;
                    font-size: 10.5px;
                    cursor: pointer;
                    white-space: nowrap;
                    transition: all 0.15s;
                }
                .pdc-chip-btn:hover {
                    background: rgba(137, 180, 250, 0.3);
                    border-color: #89b4fa;
                }

                .pdc-input-bar {
                    display: flex;
                    gap: 10px;
                    padding: 12px 16px;
                    background: rgba(20, 24, 38, 0.70);
                    border-top: 1px solid rgba(255, 255, 255, 0.08);
                }

                .pdc-input {
                    flex: 1;
                    background: rgba(10, 12, 20, 0.7);
                    border: 1px solid rgba(203, 166, 247, 0.35);
                    border-radius: 8px;
                    color: #fff;
                    font-size: 12.5px;
                    padding: 9px 14px;
                    outline: none;
                    font-family: 'Fira Code', monospace;
                }
                .pdc-input:focus {
                    border-color: #cba6f7;
                    box-shadow: 0 0 12px rgba(203, 166, 247, 0.3);
                }

                .pdc-send-btn {
                    background: #cba6f7;
                    border: none;
                    color: #11111b;
                    font-weight: 700;
                    font-size: 12px;
                    padding: 0 16px;
                    border-radius: 8px;
                    cursor: pointer;
                    transition: all 0.15s;
                }
                .pdc-send-btn:hover {
                    background: #d4bbf9;
                    transform: scale(1.03);
                }
            `;
            document.head.appendChild(style);
        }

        registrarAtajos() {
            window.addEventListener('keydown', (e) => {
                // Al presionar Escape: Restaurar inmediatamente el código minimizado
                if (e.key === 'Escape' && this.activo) {
                    e.preventDefault();
                    e.stopPropagation();
                    this.desactivar();
                    return;
                }

                if (e.key === 'Control') this.teclasPresionadas.ctrl = true;
                if (e.key === 'Alt') this.teclasPresionadas.alt = true;

                // Detección de pulsación simultánea de Ctrl + Alt
                const tieneCtrl = e.ctrlKey || this.teclasPresionadas.ctrl;
                const tieneAlt = e.altKey || this.teclasPresionadas.alt;

                if (tieneCtrl && tieneAlt) {
                    const ahora = performance.now();
                    if (ahora - this._ultimoToggle > 250) {
                        this._ultimoToggle = ahora;
                        this.alternar();
                    }
                }
            }, { capture: true });

            window.addEventListener('keyup', (e) => {
                if (e.key === 'Control') this.teclasPresionadas.ctrl = false;
                if (e.key === 'Alt') this.teclasPresionadas.alt = false;
            }, { capture: true });
        }

        alternar() {
            if (this.activo) {
                this.desactivar();
            } else {
                this.activar();
            }
        }

        activar() {
            this.activo = true;
            document.body.classList.add('prig-modo-fondo-activo');
            
            // 1. Mostrar Minimapa en la esquina superior izquierda
            this.mostrarMinimapaCodigo();

            // 2. Mostrar Diálogo Interactivo Central con el modelo
            this.mostrarDialogoCentral();

            // 3. Abrir el panel del Cerebro IA
            if (window.CerebroMemoria && typeof window.CerebroMemoria.abrirPanel === 'function') {
                window.CerebroMemoria.abrirPanel('dialogos');
            }

            window.dispatchEvent(new CustomEvent('prig:modo-cerebro-fondo', { detail: { activo: true } }));
        }

        desactivar() {
            this.activo = false;
            document.body.classList.remove('prig-modo-fondo-activo');

            // Ocultar minimapa y diálogo central
            this.ocultarMinimapaCodigo();
            this.ocultarDialogoCentral();

            // Cerrar Cerebro IA si estaba abierto
            if (window.CerebroMemoria && typeof window.CerebroMemoria.cerrarPanel === 'function') {
                window.CerebroMemoria.cerrarPanel();
            }

            // Devolver foco a Monaco Editor
            setTimeout(() => {
                if (window.editorMgr && window.editorMgr.editor && typeof window.editorMgr.editor.focus === 'function') {
                    window.editorMgr.editor.focus();
                }
            }, 100);

            window.dispatchEvent(new CustomEvent('prig:modo-cerebro-fondo', { detail: { activo: false } }));
        }

        /** Renderiza y muestra el Minimapa de Código en la esquina superior izquierda */
        mostrarMinimapaCodigo() {
            let minimapa = document.getElementById('prig-minimapa-codigo-flotante');
            if (!minimapa) {
                minimapa = document.createElement('div');
                minimapa.id = 'prig-minimapa-codigo-flotante';
                minimapa.onclick = () => this.desactivar();
                document.body.appendChild(minimapa);
            }

            // Extraer líneas de código del editor actual para el preview
            let lineasPreview = 'def main():\n    print("Prig IDE")\n    # Código activo...';
            let nombreArchivo = 'main.py';

            if (window.editorMgr && window.editorMgr.editor) {
                const model = window.editorMgr.editor.getModel();
                if (model) {
                    const lines = model.getLinesContent();
                    lineasPreview = lines.slice(0, 14).join('\n') || lineasPreview;
                }
                nombreArchivo = window.editorMgr.activePath ? window.editorMgr.activePath.split('/').pop() : 'main.py';
            }

            minimapa.innerHTML = `
                <div class="pmc-header">
                    <div style="display:flex; align-items:center; gap:6px;">
                        <i class="fa-solid fa-code" style="color:#89b4fa;"></i>
                        <span>${this.escaparHtml(nombreArchivo)}</span>
                    </div>
                    <span class="pmc-badge">MINIMAPA · ESC</span>
                </div>
                <div class="pmc-preview">
                    <pre style="margin:0; font-family:inherit; font-size:inherit; color:inherit;">${this.escaparHtml(lineasPreview)}</pre>
                    <div class="pmc-preview-overlay">
                        <i class="fa-solid fa-expand" style="margin-right:4px;"></i> Clic o ESC para restaurar código
                    </div>
                </div>
            `;
            minimapa.classList.add('visible');
        }

        ocultarMinimapaCodigo() {
            const minimapa = document.getElementById('prig-minimapa-codigo-flotante');
            if (minimapa) minimapa.classList.remove('visible');
        }

        /** Renderiza y muestra el Cuadro de Diálogo Interactivo Central con el Modelo */
        mostrarDialogoCentral() {
            let dialogo = document.getElementById('prig-dialogo-central-modelo');
            if (!dialogo) {
                dialogo = document.createElement('div');
                dialogo.id = 'prig-dialogo-central-modelo';
                document.body.appendChild(dialogo);
            }

            // Obtener datos del director y personaje activo
            let nombrePersonaje = 'Titán Mecha MK-VII';
            let textoDialogo = 'Analizando arquitectura, dependencias y flujo de control en tiempo real...';
            if (window.DIRECTOR_ASCII && window.DIRECTOR_ASCII.evaluador) {
                nombrePersonaje = window.DIRECTOR_ASCII.evaluador.nombre || nombrePersonaje;
                if (window.DIRECTOR_ASCII.evaluador.dialogo && window.DIRECTOR_ASCII.evaluador.dialogo.texto) {
                    textoDialogo = window.DIRECTOR_ASCII.evaluador.dialogo.texto;
                }
            }

            dialogo.innerHTML = `
                <div class="pdc-header">
                    <div style="display: flex; align-items: center; gap: 10px;">
                        <div style="width: 30px; height: 30px; border-radius: 8px; background: rgba(203, 166, 247, 0.2); border: 1px solid #cba6f7; display: flex; align-items: center; justify-content: center;">
                            <i class="fa-solid fa-brain" style="color: #cba6f7; font-size: 15px;"></i>
                        </div>
                        <div>
                            <div style="font-weight: 800; font-size: 13px; color: #ffffff; letter-spacing: 0.5px;">🧠 [${this.escaparHtml(nombrePersonaje.toUpperCase())}]</div>
                            <div style="font-size: 10px; color: #a6e3a1; font-family: 'Fira Code', monospace;">⚡ 7B LLM DIRECTOR · ONLINE</div>
                        </div>
                    </div>
                    <div style="display: flex; align-items: center; gap: 6px;">
                        <button onclick="window.modoCerebroFondo.desactivar();" title="Volver al Código (Esc)" style="background: none; border: none; color: #a6adc8; font-size: 16px; cursor: pointer; padding: 4px 8px; border-radius: 4px; transition: color 0.15s;">
                            <i class="fa-solid fa-xmark"></i>
                        </button>
                    </div>
                </div>

                <div class="pdc-tabs">
                    <button class="pdc-tab-btn activo" onclick="window.modoCerebroFondo.cambiarTabDialogo('dialogo', this)">💬 Diálogo Activo</button>
                    <button class="pdc-tab-btn" onclick="window.modoCerebroFondo.cambiarTabDialogo('tips', this)">⚡ Consejos & Tips</button>
                    <button class="pdc-tab-btn" onclick="window.modoCerebroFondo.cambiarTabDialogo('flujo', this)">🔀 Flujo de Código</button>
                    <button class="pdc-tab-btn" onclick="window.modoCerebroFondo.cambiarTabDialogo('chat', this)">✨ Chat con el Modelo</button>
                </div>

                <div class="pdc-body" id="pdc-dialogo-body">
                    <div class="pdc-chat-msg modelo" id="pdc-stream-texto">
                        <div style="color: #cba6f7; font-weight: 700; margin-bottom: 6px; font-size: 11px;">
                            💬 RAZONAMIENTO Y EVALUACIÓN:
                        </div>
                        <div id="pdc-texto-evaluacion">${this.escaparHtml(textoDialogo)}</div>
                    </div>
                </div>

                <div class="pdc-chips">
                    <button class="pdc-chip-btn" onclick="window.modoCerebroFondo.enviarPromptRapido('Explica la arquitectura y las funciones de este archivo')">🔍 Explicar archivo</button>
                    <button class="pdc-chip-btn" onclick="window.modoCerebroFondo.enviarPromptRapido('¿Dónde hay cuellos de botella o bugs potenciales?')">🐛 Detectar bugs</button>
                    <button class="pdc-chip-btn" onclick="window.modoCerebroFondo.enviarPromptRapido('Sugerir refactorización limpia y buenas prácticas')">⚡ Sugerir refactor</button>
                    <button class="pdc-chip-btn" onclick="window.modoCerebroFondo.enviarPromptRapido('Genera un flujo paso a paso de ejecución')">🔀 Flujo de ejecución</button>
                </div>

                <div class="pdc-input-bar">
                    <input type="text" id="prig-input-dialogo-central" class="pdc-input" placeholder="Escribe un mensaje o pregunta al modelo 7B... (Enter para enviar)" onkeydown="if(event.key==='Enter') window.modoCerebroFondo.enviarMensajeCentral();" />
                    <button class="pdc-send-btn" onclick="window.modoCerebroFondo.enviarMensajeCentral();">
                        <i class="fa-solid fa-paper-plane"></i>
                    </button>
                </div>
            `;
            dialogo.classList.add('visible');

            // Auto-focus al campo de texto
            setTimeout(() => {
                const input = document.getElementById('prig-input-dialogo-central');
                if (input) input.focus();
            }, 100);
        }

        ocultarDialogoCentral() {
            const dialogo = document.getElementById('prig-dialogo-central-modelo');
            if (dialogo) dialogo.classList.remove('visible');
        }

        cambiarTabDialogo(tab, btn) {
            document.querySelectorAll('.pdc-tab-btn').forEach(b => b.classList.remove('activo'));
            if (btn) btn.classList.add('activo');

            const body = document.getElementById('pdc-dialogo-body');
            if (!body) return;

            if (tab === 'dialogo') {
                let texto = 'Evaluando código y telemetría...';
                if (window.DIRECTOR_ASCII && window.DIRECTOR_ASCII.evaluador && window.DIRECTOR_ASCII.evaluador.dialogo) {
                    texto = window.DIRECTOR_ASCII.evaluador.dialogo.texto;
                }
                body.innerHTML = `
                    <div class="pdc-chat-msg modelo">
                        <div style="color: #cba6f7; font-weight: 700; margin-bottom: 6px; font-size: 11px;">💬 RAZONAMIENTO Y EVALUACIÓN:</div>
                        <div>${this.escaparHtml(texto)}</div>
                    </div>
                `;
            } else if (tab === 'tips') {
                let tip = { categoria: 'Clean Architecture', titulo: 'Modularización', detalle: 'Aplica validación temprana de parámetros nulos para simplificar el flujo.', sugerencia_codigo: 'if not params: return fallback_state' };
                if (window.DIRECTOR_ASCII && window.DIRECTOR_ASCII.evaluador && window.DIRECTOR_ASCII.evaluador.consejo) {
                    tip = window.DIRECTOR_ASCII.evaluador.consejo;
                }
                body.innerHTML = `
                    <div class="pdc-chat-msg modelo">
                        <div style="color: #f9e2af; font-weight: 700; margin-bottom: 4px; font-size: 11px;">🏷️ CATEGORÍA: ${this.escaparHtml(tip.categoria || 'Clean Code')}</div>
                        <div style="color: #89b4fa; font-weight: 700; margin-bottom: 6px; font-size: 12px;">📌 ${this.escaparHtml(tip.titulo || 'Optimización')}</div>
                        <div style="margin-bottom: 10px;">${this.escaparHtml(tip.detalle || '')}</div>
                        ${tip.sugerencia_codigo ? `
                            <div style="background: rgba(10,12,20,0.85); border: 1px solid #89b4fa; padding: 8px 10px; border-radius: 6px; color: #a6e3a1; font-family:'Fira Code',monospace; font-size:11px;">
                                <code>${this.escaparHtml(tip.sugerencia_codigo)}</code>
                            </div>
                        ` : ''}
                    </div>
                `;
            } else if (tab === 'flujo') {
                const pasos = (window.DIRECTOR_ASCII && window.DIRECTOR_ASCII.evaluador && window.DIRECTOR_ASCII.evaluador.flujoGrafico) ? window.DIRECTOR_ASCII.evaluador.flujoGrafico.pasos : [];
                body.innerHTML = `
                    <div style="display:flex; flex-direction:column; gap:8px;">
                        <div style="color:#cba6f7; font-weight:700; font-size:11px; font-family:'Fira Code',monospace;">🔀 PASOS DEL FLUJO DE EJECUCIÓN:</div>
                        ${pasos.map((p, i) => `
                            <div style="background: rgba(24,24,37,0.9); border: 1px solid #45475a; border-radius: 6px; padding: 8px 12px; font-size: 11px; font-family:'Fira Code',monospace;">
                                <div style="display:flex; justify-content:space-between; color:#89b4fa; font-weight:700; margin-bottom:4px;">
                                    <span>${p.icono || '⚡'} Paso ${i + 1}: ${this.escaparHtml(p.etiqueta)}</span>
                                    <span style="color:#a6adc8;">L${p.linea_inicio}-${p.linea_fin}</span>
                                </div>
                                <div style="color:#cdd6f4;">${this.escaparHtml(p.explicacion)}</div>
                            </div>
                        `).join('') || '<div style="color:#6c7086;">Cargando flujo de análisis...</div>'}
                    </div>
                `;
            } else if (tab === 'chat') {
                body.innerHTML = `
                    <div class="pdc-chat-msg modelo">
                        <div style="color: #cba6f7; font-weight: 700; margin-bottom: 4px;">🧠 CHAT CON EL MODELO 7B:</div>
                        <div>Escribe cualquier duda sobre tu código o arquitectura en el campo inferior.</div>
                    </div>
                `;
            }
        }

        enviarPromptRapido(prompt) {
            const input = document.getElementById('prig-input-dialogo-central');
            if (input) {
                input.value = prompt;
                this.enviarMensajeCentral();
            }
        }

        async enviarMensajeCentral() {
            const input = document.getElementById('prig-input-dialogo-central');
            const body = document.getElementById('pdc-dialogo-body');
            if (!input || !body) return;

            const pregunta = input.value.trim();
            if (!pregunta) return;

            input.value = '';

            // Renderizar mensaje del usuario
            body.innerHTML += `
                <div class="pdc-chat-msg usuario">
                    <div>${this.escaparHtml(pregunta)}</div>
                </div>
                <div class="pdc-chat-msg modelo" id="pdc-loading-msg">
                    <div style="color: #cba6f7; font-weight: 700; margin-bottom: 4px;">
                        <i class="fa-solid fa-spinner fa-spin"></i> Razonando con memoria AST...
                    </div>
                </div>
            `;
            body.scrollTop = body.scrollHeight;

            try {
                const resp = await fetch('/api/llm/preguntar_cerebro', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        pregunta: pregunta,
                        modelo: 'qwen2.5-coder:7b',
                        endpoint: 'http://localhost:11434'
                    })
                });

                const loader = document.getElementById('pdc-loading-msg');
                if (loader) loader.remove();

                if (resp.ok) {
                    const data = await resp.json();
                    const respuesta = data.respuesta || 'Sin respuesta del modelo.';
                    body.innerHTML += `
                        <div class="pdc-chat-msg modelo">
                            <div style="display:flex; justify-content:space-between; color: #cba6f7; font-weight: 700; margin-bottom: 6px; font-size: 11px;">
                                <span>🧠 7B DIRECTOR:</span>
                                <span style="color:#a6e3a1; font-size:10px;">⚡ Ahorro: ${data.ahorro_porcentaje || 92}%</span>
                            </div>
                            <div style="white-space: pre-wrap;">${this.escaparHtml(respuesta)}</div>
                        </div>
                    `;

                    // Sincronizar el diálogo en el personaje evaluador
                    if (window.DIRECTOR_ASCII && window.DIRECTOR_ASCII.evaluador) {
                        window.DIRECTOR_ASCII.evaluador.dialogo = {
                            texto: respuesta.slice(0, 180),
                            charIndex: respuesta.length,
                            ultimoCharTime: performance.now()
                        };
                    }
                } else {
                    body.innerHTML += `<div class="pdc-chat-msg modelo" style="color:#f38ba8;">⚠️ Error al conectar con el modelo local.</div>`;
                }
            } catch (e) {
                const loader = document.getElementById('pdc-loading-msg');
                if (loader) loader.remove();
                body.innerHTML += `<div class="pdc-chat-msg modelo" style="color:#f38ba8;">⚠️ Error en la consulta: ${this.escaparHtml(e.message)}</div>`;
            }

            body.scrollTop = body.scrollHeight;
        }

        escaparHtml(str) {
            if (!str) return '';
            return String(str)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }
    }

    // Instancia global
    if (typeof window !== 'undefined') {
        window.CerebroMemoria = new CerebroMemoriaManager();
        window.modoCerebroFondo = new ModoCerebroFondoManager();
        document.addEventListener('DOMContentLoaded', () => {
            window.CerebroMemoria.init();
        });
    }

})(typeof window !== 'undefined' ? window : globalThis);

