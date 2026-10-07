/**
 * ============================================================================
 * PRIG IDE - MENÚ DESLIZANTE DE ARCHIVOS AL APRETAR LA RUEDA DEL MOUSE
 * ============================================================================
 * Despliega un menú flotante deslizante exactamente sobre el cursor del mouse
 * cuando el usuario presiona la rueda (botón central / middle-click).
 * 
 * Características:
 * - Detección inteligente de botón central (event.button === 1 / auxclick).
 * - Animación deslizante suave con física de entrada y desenfoque glassmorphism.
 * - Exploración de todos los archivos del directorio de trabajo activo.
 * - Búsqueda rápida en tiempo real con resaltado y filtros por tipo (Python, Notebooks, JS, etc.).
 * - Historial de archivos recientes en la cabecera.
 * - Navegación total por teclado (Flechas Arriba/Abajo, Enter para abrir, Escape para cerrar).
 * - Apertura instantánea en Monaco Editor con 1 clic.
 * - Totalmente configurable por el usuario (disparador, estilo visual, límites, activación).
 */

(function () {
    'use strict';

    class MenuRuedaArchivos {
        constructor() {
            this.id = 'prig-menu-rueda-archivos';
            this.activo = false;
            this.indiceSeleccionado = 0;
            this.categoriaFiltro = 'todos';
            this.terminoBusqueda = '';
            this.archivosPlanos = [];
            this.archivosFiltrados = [];
            this.posicionMouse = { x: 0, y: 0 };
            this.config = this.cargarConfig();

            this.inicializarEstilos();
            this.registrarEventos();
        }

        /** Carga la configuración guardada en LocalStorage o valores por defecto */
        cargarConfig() {
            const defaultCfg = {
                habilitado: true,
                disparador: 'rueda_click', // 'rueda_click' | 'alt_click' | 'shift_click' | 'doble_rueda'
                estilo: 'deslizante_neon',  // 'deslizante_neon' | 'cristal_oscuro' | 'minimalista'
                maxItems: 12,
                mostrarRecientes: true,
                busquedaRapida: true,
                autocerrarAlPerderFoco: true
            };
            try {
                const guardado = localStorage.getItem('prig_menu_rueda_cfg');
                if (guardado) {
                    return { ...defaultCfg, ...JSON.parse(guardado) };
                }
            } catch (e) {
                console.warn('Error leyendo prig_menu_rueda_cfg:', e);
            }
            return defaultCfg;
        }

        /** Guarda y aplica una nueva configuración */
        guardarConfig(nuevaCfg) {
            this.config = { ...this.config, ...nuevaCfg };
            try {
                localStorage.setItem('prig_menu_rueda_cfg', JSON.stringify(this.config));
            } catch (e) {
                console.warn('Error guardando prig_menu_rueda_cfg:', e);
            }
        }

        /** Registra los estilos CSS embebidos para animaciones deslizantes y glassmorphism */
        inicializarEstilos() {
            if (document.getElementById('prig-menu-rueda-css')) return;
            const style = document.createElement('style');
            style.id = 'prig-menu-rueda-css';
            style.textContent = `
                #prig-menu-rueda-archivos {
                    position: fixed;
                    z-index: 999999;
                    width: 380px;
                    max-height: 480px;
                    background: rgba(18, 20, 29, 0.94);
                    backdrop-filter: blur(16px);
                    -webkit-backdrop-filter: blur(16px);
                    border: 1px solid rgba(137, 180, 250, 0.35);
                    border-radius: 12px;
                    box-shadow: 0 16px 40px rgba(0, 0, 0, 0.65), 0 0 25px rgba(137, 180, 250, 0.18);
                    display: flex;
                    flex-direction: column;
                    overflow: hidden;
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                    color: #cdd6f4;
                    transform-origin: top left;
                    opacity: 0;
                    transform: translateY(-12px) scale(0.96);
                    transition: opacity 0.18s cubic-bezier(0.16, 1, 0.3, 1), transform 0.18s cubic-bezier(0.16, 1, 0.3, 1);
                    pointer-events: none;
                    user-select: none;
                }

                #prig-menu-rueda-archivos.visible {
                    opacity: 1;
                    transform: translateY(0) scale(1);
                    pointer-events: auto;
                }

                #prig-menu-rueda-archivos.estilo-cristal_oscuro {
                    background: rgba(15, 17, 23, 0.96);
                    border-color: rgba(255, 255, 255, 0.12);
                    box-shadow: 0 20px 45px rgba(0, 0, 0, 0.75);
                }

                #prig-menu-rueda-archivos.estilo-minimalista {
                    background: #181825;
                    border: 1px solid #313244;
                    box-shadow: 0 8px 24px rgba(0,0,0,0.5);
                    border-radius: 8px;
                }

                .pmr-header {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    padding: 10px 14px 6px 14px;
                    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
                    background: rgba(255, 255, 255, 0.02);
                }

                .pmr-titulo {
                    font-size: 11px;
                    font-weight: 700;
                    text-transform: uppercase;
                    letter-spacing: 0.8px;
                    color: #89b4fa;
                    display: flex;
                    align-items: center;
                    gap: 6px;
                }

                .pmr-badge-cnt {
                    font-size: 10px;
                    background: rgba(137, 180, 250, 0.15);
                    color: #89b4fa;
                    padding: 1px 6px;
                    border-radius: 10px;
                }

                .pmr-close-btn {
                    background: none;
                    border: none;
                    color: #6c7086;
                    cursor: pointer;
                    font-size: 13px;
                    padding: 2px 6px;
                    border-radius: 4px;
                    transition: all 0.15s;
                }
                .pmr-close-btn:hover {
                    color: #f38ba8;
                    background: rgba(243, 139, 168, 0.15);
                }

                .pmr-search-box {
                    padding: 8px 12px;
                    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
                    position: relative;
                }

                .pmr-search-input {
                    width: 100%;
                    box-sizing: border-box;
                    padding: 7px 10px 7px 28px;
                    background: rgba(17, 17, 27, 0.8);
                    border: 1px solid rgba(137, 180, 250, 0.25);
                    border-radius: 6px;
                    color: #fff;
                    font-size: 12px;
                    font-family: 'Fira Code', monospace;
                    outline: none;
                    transition: border-color 0.15s, box-shadow 0.15s;
                }
                .pmr-search-input:focus {
                    border-color: #89b4fa;
                    box-shadow: 0 0 8px rgba(137, 180, 250, 0.3);
                }
                .pmr-search-icon {
                    position: absolute;
                    left: 20px;
                    top: 17px;
                    color: #6c7086;
                    font-size: 11px;
                    pointer-events: none;
                }

                .pmr-tabs {
                    display: flex;
                    gap: 4px;
                    padding: 6px 12px 4px 12px;
                    overflow-x: auto;
                    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
                }

                .pmr-tab-btn {
                    background: transparent;
                    border: 1px solid transparent;
                    color: #a6adc8;
                    font-size: 10px;
                    padding: 3px 8px;
                    border-radius: 4px;
                    cursor: pointer;
                    white-space: nowrap;
                    transition: all 0.15s;
                }
                .pmr-tab-btn:hover {
                    color: #fff;
                    background: rgba(255, 255, 255, 0.05);
                }
                .pmr-tab-btn.activo {
                    background: rgba(137, 180, 250, 0.2);
                    border-color: rgba(137, 180, 250, 0.4);
                    color: #89b4fa;
                    font-weight: 600;
                }

                .pmr-list {
                    flex: 1;
                    overflow-y: auto;
                    padding: 6px;
                    max-height: 320px;
                    display: flex;
                    flex-direction: column;
                    gap: 2px;
                }

                .pmr-list::-webkit-scrollbar {
                    width: 5px;
                }
                .pmr-list::-webkit-scrollbar-thumb {
                    background: rgba(255, 255, 255, 0.15);
                    border-radius: 4px;
                }

                .pmr-item {
                    display: flex;
                    align-items: center;
                    gap: 10px;
                    padding: 6px 10px;
                    border-radius: 6px;
                    cursor: pointer;
                    transition: background 0.12s, transform 0.1s, border-left 0.12s;
                    border-left: 3px solid transparent;
                }
                .pmr-item:hover, .pmr-item.seleccionado {
                    background: rgba(137, 180, 250, 0.14);
                    border-left-color: #89b4fa;
                    transform: translateX(2px);
                }
                .pmr-item.es-reciente {
                    background: rgba(249, 226, 175, 0.05);
                }

                .pmr-item-icon {
                    font-size: 14px;
                    width: 18px;
                    text-align: center;
                    flex-shrink: 0;
                }

                .pmr-item-info {
                    flex: 1;
                    min-width: 0;
                    display: flex;
                    flex-direction: column;
                }

                .pmr-item-name {
                    font-size: 12px;
                    font-weight: 500;
                    color: #cdd6f4;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                }

                .pmr-item.seleccionado .pmr-item-name {
                    color: #ffffff;
                    font-weight: 600;
                }

                .pmr-item-path {
                    font-size: 10px;
                    color: #6c7086;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                }

                .pmr-badge-type {
                    font-size: 9px;
                    font-weight: bold;
                    padding: 2px 5px;
                    border-radius: 3px;
                    text-transform: uppercase;
                    flex-shrink: 0;
                }

                .pmr-footer {
                    padding: 6px 12px;
                    border-top: 1px solid rgba(255, 255, 255, 0.06);
                    background: rgba(0, 0, 0, 0.2);
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    font-size: 10px;
                    color: #6c7086;
                }

                .pmr-keys-hint {
                    display: flex;
                    gap: 8px;
                }
                .pmr-kbd {
                    background: rgba(255, 255, 255, 0.08);
                    padding: 1px 4px;
                    border-radius: 3px;
                    color: #a6adc8;
                    border: 1px solid rgba(255, 255, 255, 0.1);
                }

                .pmr-empty-state {
                    padding: 24px;
                    text-align: center;
                    color: #6c7086;
                    font-size: 12px;
                }
            `;
            document.head.appendChild(style);
        }

        /** Registra escuchadores de eventos para disparo por mouse y teclado */
        registrarEventos() {
            let ultimoDisparoTiempo = 0;
            this.tiempoApertura = 0;

            const procesarDisparoMouse = (e) => {
                this.posicionMouse = { x: e.clientX, y: e.clientY };
                if (!this.config.habilitado) return;

                const ahora = performance.now();
                if (ahora - ultimoDisparoTiempo < 200) return; // Evitar disparos duplicados rápidos (mousedown + auxclick)

                const disparador = this.config.disparador;
                let debeAbrir = false;

                if (disparador === 'rueda_click' && e.button === 1) {
                    debeAbrir = true;
                } else if (disparador === 'alt_click' && e.button === 0 && e.altKey) {
                    debeAbrir = true;
                } else if (disparador === 'shift_click' && e.button === 0 && e.shiftKey) {
                    debeAbrir = true;
                } else if (disparador === 'doble_rueda' && e.button === 1) {
                    if (ahora - this._ultimoClickRueda < 350) {
                        debeAbrir = true;
                    }
                    this._ultimoClickRueda = ahora;
                }

                if (debeAbrir) {
                    e.preventDefault();
                    e.stopPropagation();
                    ultimoDisparoTiempo = ahora;
                    this.tiempoApertura = ahora;
                    this.abrirMenu(e.clientX, e.clientY);
                }
            };

            // Evento mousedown para abrir con la rueda y para cerrar si se da clic afuera
            window.addEventListener('mousedown', (e) => {
                // Si es clic con la rueda (botón central = 1)
                if (e.button === 1 && this.config.habilitado) {
                    e.preventDefault();
                    procesarDisparoMouse(e);
                    return;
                }

                // Si ya está abierto y se hace clic afuera del menú, cerrarlo de inmediato
                if (this.activo) {
                    const ahora = performance.now();
                    if (ahora - this.tiempoApertura > 100) {
                        const menuEl = document.getElementById(this.id);
                        if (menuEl && !menuEl.contains(e.target)) {
                            this.cerrarMenu();
                        }
                    }
                }
            }, { capture: true });

            // auxclick auxiliar para navegadores que separan el botón central
            window.addEventListener('auxclick', (e) => {
                if (e.button === 1 && this.config.habilitado) {
                    e.preventDefault();
                    procesarDisparoMouse(e);
                }
            }, { capture: true });

            // Registrar atajo de teclado alternativo Escape y navegación
            window.addEventListener('keydown', (e) => {
                if (!this.activo) return;

                if (e.key === 'Escape') {
                    e.preventDefault();
                    this.cerrarMenu();
                } else if (e.key === 'ArrowDown') {
                    e.preventDefault();
                    this.moverSeleccion(+1);
                } else if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    this.moverSeleccion(-1);
                } else if (e.key === 'Enter') {
                    e.preventDefault();
                    this.abrirItemSeleccionado();
                }
            }, { capture: true });

            // Cerrar menú al redimensionar ventana
            window.addEventListener('resize', () => {
                if (this.activo) this.cerrarMenu();
            });
        }

        /** Obtiene la lista completa de archivos del proyecto aplanada recursivamente */
        async obtenerArchivosWorkspace() {
            let rawTree = [];
            if (window.fileTreeMgr && window.fileTreeMgr.rawTreeData && window.fileTreeMgr.rawTreeData.length > 0) {
                rawTree = window.fileTreeMgr.rawTreeData;
            } else {
                try {
                    const res = await fetch('/api/tree');
                    if (res.ok) {
                        rawTree = await res.json();
                        if (window.fileTreeMgr) window.fileTreeMgr.rawTreeData = rawTree;
                    }
                } catch (e) {
                    console.warn('No se pudo obtener el árbol de archivos:', e);
                }
            }

            const lista = [];
            const recorrer = (nodos, dirPadre = '') => {
                if (!Array.isArray(nodos)) return;
                for (const item of nodos) {
                    if (item.is_dir) {
                        recorrer(item.children || [], item.path || (dirPadre ? `${dirPadre}/${item.name}` : item.name));
                    } else {
                        const meta = this.obtenerMetaArchivo(item.name);
                        lista.push({
                            name: item.name,
                            path: item.path || (dirPadre ? `${dirPadre}/${item.name}` : item.name),
                            parentDir: dirPadre || '.',
                            ext: meta.ext,
                            icon: meta.icon,
                            color: meta.color,
                            badge: meta.badge,
                            badgeBg: meta.badgeBg,
                            tipoGrupo: meta.grupo
                        });
                    }
                }
            };

            recorrer(rawTree);
            this.archivosPlanos = lista;
            return lista;
        }

        /** Determina iconos, colores y categorías según la extensión */
        obtenerMetaArchivo(nombre) {
            const ext = (nombre.split('.').pop() || '').toLowerCase();
            switch (ext) {
                case 'py':
                case 'pyw':
                    return { ext, icon: 'fa-brands fa-python', color: '#89dceb', badge: 'PY', badgeBg: 'rgba(137,220,235,0.2)', grupo: 'python' };
                case 'ipynb':
                    return { ext, icon: 'fa-solid fa-book-bookmark', color: '#fab387', badge: 'NB', badgeBg: 'rgba(250,179,135,0.2)', grupo: 'notebooks' };
                case 'js':
                case 'mjs':
                case 'cjs':
                    return { ext, icon: 'fa-brands fa-js', color: '#f9e2af', badge: 'JS', badgeBg: 'rgba(249,226,175,0.2)', grupo: 'web' };
                case 'ts':
                case 'tsx':
                    return { ext, icon: 'fa-solid fa-code', color: '#89b4fa', badge: 'TS', badgeBg: 'rgba(137,180,250,0.2)', grupo: 'web' };
                case 'html':
                case 'htm':
                    return { ext, icon: 'fa-brands fa-html5', color: '#f38ba8', badge: 'HTML', badgeBg: 'rgba(243,139,168,0.2)', grupo: 'web' };
                case 'css':
                case 'scss':
                case 'less':
                    return { ext, icon: 'fa-brands fa-css3-alt', color: '#74c7ec', badge: 'CSS', badgeBg: 'rgba(116,199,236,0.2)', grupo: 'web' };
                case 'json':
                case 'yaml':
                case 'yml':
                case 'toml':
                    return { ext, icon: 'fa-solid fa-sliders', color: '#cba6f7', badge: 'CFG', badgeBg: 'rgba(203,166,247,0.2)', grupo: 'config' };
                case 'md':
                case 'markdown':
                case 'txt':
                    return { ext, icon: 'fa-solid fa-file-lines', color: '#a6e3a1', badge: 'DOC', badgeBg: 'rgba(166,227,161,0.2)', grupo: 'docs' };
                case 'sh':
                case 'bash':
                case 'zsh':
                    return { ext, icon: 'fa-solid fa-terminal', color: '#a6e3a1', badge: 'SH', badgeBg: 'rgba(166,227,161,0.2)', grupo: 'scripts' };
                case 'c':
                case 'cpp':
                case 'h':
                case 'hpp':
                    return { ext, icon: 'fa-solid fa-microchip', color: '#89b4fa', badge: 'C/C++', badgeBg: 'rgba(137,180,250,0.2)', grupo: 'otros' };
                case 'rs':
                    return { ext, icon: 'fa-solid fa-gear', color: '#fab387', badge: 'RUST', badgeBg: 'rgba(250,179,135,0.2)', grupo: 'otros' };
                case 'sql':
                    return { ext, icon: 'fa-solid fa-database', color: '#f9e2af', badge: 'SQL', badgeBg: 'rgba(249,226,175,0.2)', grupo: 'otros' };
                default:
                    return { ext, icon: 'fa-solid fa-file-code', color: '#bac2de', badge: ext.toUpperCase() || 'FILE', badgeBg: 'rgba(186,194,222,0.15)', grupo: 'otros' };
            }
        }

        /** Obtiene la lista de archivos abiertos recientemente */
        obtenerArchivosRecientes() {
            try {
                const raw = localStorage.getItem('prig_recent_files');
                if (raw) return JSON.parse(raw);
            } catch (e) {
                console.warn('Error leyendo prig_recent_files:', e);
            }
            return [];
        }

        /** Agrega un archivo a la lista de recientes */
        registrarArchivoReciente(path, name) {
            try {
                let rec = this.obtenerArchivosRecientes().filter(item => item.path !== path);
                rec.unshift({ path, name, time: Date.now() });
                if (rec.length > 20) rec = rec.slice(0, 20);
                localStorage.setItem('prig_recent_files', JSON.stringify(rec));
            } catch (e) {
                console.warn('Error guardando reciente:', e);
            }
        }

        /** Abre y posiciona el menú deslizante en las coordenadas exactas del ratón */
        async abrirMenu(clientX, clientY) {
            let el = document.getElementById(this.id);
            if (!el) {
                el = document.createElement('div');
                el.id = this.id;
                document.body.appendChild(el);
            }

            // Aplicar clase de estilo visual
            el.className = `visible estilo-${this.config.estilo}`;

            // Cargar archivos del workspace
            await this.obtenerArchivosWorkspace();

            this.categoriaFiltro = 'todos';
            this.terminoBusqueda = '';
            this.indiceSeleccionado = 0;

            this.renderContenido(el);

            // Ajustar posición para que nunca quede fuera de la pantalla (Viewport Bounding)
            requestAnimationFrame(() => {
                const ancho = el.offsetWidth || 380;
                const alto = el.offsetHeight || 420;
                const margen = 16;

                let posX = clientX - 20; // Un poco a la derecha del cursor
                let posY = clientY - 15; // Ligeramente bajo la rueda

                if (posX + ancho > window.innerWidth - margen) {
                    posX = window.innerWidth - ancho - margen;
                }
                if (posX < margen) posX = margen;

                if (posY + alto > window.innerHeight - margen) {
                    posY = window.innerHeight - alto - margen;
                }
                if (posY < margen) posY = margen;

                el.style.left = `${posX}px`;
                el.style.top = `${posY}px`;

                // Auto-enfocar el campo de búsqueda si está habilitado
                const searchInput = el.querySelector('.pmr-search-input');
                if (searchInput && this.config.busquedaRapida) {
                    searchInput.focus();
                    searchInput.select();
                }

                this.activo = true;
            });
        }

        /** Cierra el menú con una transición suave */
        cerrarMenu() {
            const el = document.getElementById(this.id);
            if (el) {
                el.classList.remove('visible');
                setTimeout(() => {
                    if (!this.activo && el.parentNode) {
                        el.parentNode.removeChild(el);
                    }
                }, 200);
            }
            this.activo = false;
        }

        /** Renderiza la estructura visual del menú */
        renderContenido(el) {
            const recientes = this.obtenerArchivosRecientes();
            const totalArchivos = this.archivosPlanos.length;

            el.innerHTML = `
                <div class="pmr-header">
                    <div class="pmr-titulo">
                        <i class="fa-solid fa-folder-tree" style="color: #89b4fa;"></i>
                        <span>Archivos del Proyecto</span>
                        <span class="pmr-badge-cnt" id="pmr-total-count">${totalArchivos}</span>
                    </div>
                    <div style="display: flex; align-items: center; gap: 4px;">
                        <button class="pmr-close-btn" title="Configurar Menú Rueda" onclick="window.menuRuedaArchivos.abrirConfiguracion(event)">
                            <i class="fa-solid fa-gear"></i>
                        </button>
                        <button class="pmr-close-btn" title="Cerrar (Esc)" onclick="window.menuRuedaArchivos.cerrarMenu()">
                            <i class="fa-solid fa-xmark"></i>
                        </button>
                    </div>
                </div>

                ${this.config.busquedaRapida ? `
                <div class="pmr-search-box">
                    <i class="fa-solid fa-magnifying-glass pmr-search-icon"></i>
                    <input type="text" class="pmr-search-input" placeholder="Buscar archivo o extensión... (Esc para salir)" />
                </div>
                ` : ''}

                <div class="pmr-tabs">
                    <button class="pmr-tab-btn ${this.categoriaFiltro === 'todos' ? 'activo' : ''}" data-cat="todos">Todos (${totalArchivos})</button>
                    ${recientes.length > 0 ? `<button class="pmr-tab-btn ${this.categoriaFiltro === 'recientes' ? 'activo' : ''}" data-cat="recientes">★ Recientes (${recientes.length})</button>` : ''}
                    <button class="pmr-tab-btn ${this.categoriaFiltro === 'python' ? 'activo' : ''}" data-cat="python">Python</button>
                    <button class="pmr-tab-btn ${this.categoriaFiltro === 'notebooks' ? 'activo' : ''}" data-cat="notebooks">Notebooks</button>
                    <button class="pmr-tab-btn ${this.categoriaFiltro === 'web' ? 'activo' : ''}" data-cat="web">JS / Web</button>
                </div>

                <div class="pmr-list" id="pmr-files-list">
                    <!-- Items inyectados dinámicamente -->
                </div>

                <div class="pmr-footer">
                    <div class="pmr-keys-hint">
                        <span><span class="pmr-kbd">↑</span><span class="pmr-kbd">↓</span> Navegar</span>
                        <span><span class="pmr-kbd">↵ Enter</span> Abrir</span>
                        <span><span class="pmr-kbd">Esc</span> Salir</span>
                    </div>
                    <div style="font-size: 9px; opacity: 0.8;">Prig Quick-Wheel</div>
                </div>
            `;

            // Enlazar eventos de búsqueda
            const searchInput = el.querySelector('.pmr-search-input');
            if (searchInput) {
                searchInput.addEventListener('input', (e) => {
                    this.terminoBusqueda = e.target.value.toLowerCase().trim();
                    this.indiceSeleccionado = 0;
                    this.actualizarListaItems();
                });
            }

            // Enlazar pestañas de categorías
            const tabBtns = el.querySelectorAll('.pmr-tab-btn');
            tabBtns.forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.categoriaFiltro = btn.dataset.cat;
                    tabBtns.forEach(b => b.classList.remove('activo'));
                    btn.classList.add('activo');
                    this.indiceSeleccionado = 0;
                    this.actualizarListaItems();
                });
            });

            this.actualizarListaItems();
        }

        /** Filtra y actualiza la lista de elementos en pantalla */
        actualizarListaItems() {
            const listEl = document.getElementById('pmr-files-list');
            if (!listEl) return;

            let items = [...this.archivosPlanos];

            // 1. Filtrar por categoría
            if (this.categoriaFiltro === 'recientes') {
                const recientes = this.obtenerArchivosRecientes();
                const pathsRecientes = new Set(recientes.map(r => r.path));
                items = items.filter(it => pathsRecientes.has(it.path));
            } else if (this.categoriaFiltro !== 'todos') {
                items = items.filter(it => it.tipoGrupo === this.categoriaFiltro);
            }

            // 2. Filtrar por término de búsqueda
            if (this.terminoBusqueda) {
                items = items.filter(it => 
                    it.name.toLowerCase().includes(this.terminoBusqueda) || 
                    it.path.toLowerCase().includes(this.terminoBusqueda) ||
                    it.ext.toLowerCase().includes(this.terminoBusqueda)
                );
            }

            // Límite de elementos visibles según configuración
            const maxItems = parseInt(this.config.maxItems, 10) || 12;
            this.archivosFiltrados = items;

            if (items.length === 0) {
                listEl.innerHTML = `
                    <div class="pmr-empty-state">
                        <i class="fa-solid fa-folder-open" style="font-size: 24px; opacity: 0.4; margin-bottom: 8px;"></i>
                        <div>No se encontraron archivos</div>
                        <div style="font-size: 10px; margin-top: 4px; color: #585b70;">Prueba con otro término o filtro</div>
                    </div>
                `;
                return;
            }

            const itemsVisibles = maxItems > 0 ? items.slice(0, maxItems) : items;

            listEl.innerHTML = itemsVisibles.map((item, index) => {
                const esSeleccionado = index === this.indiceSeleccionado;
                const esReciente = this.categoriaFiltro === 'recientes';
                const nombreSeguro = this.escaparHtml(item.name);
                const rutaSegura = this.escaparHtml(item.parentDir);

                return `
                    <div class="pmr-item ${esSeleccionado ? 'seleccionado' : ''} ${esReciente ? 'es-reciente' : ''}" 
                         data-index="${index}" 
                         data-path="${this.escaparHtml(item.path)}" 
                         data-name="${nombreSeguro}"
                         onclick="window.menuRuedaArchivos.abrirArchivo('${this.escaparJs(item.path)}', '${this.escaparJs(item.name)}')">
                        <i class="${item.icon} pmr-item-icon" style="color: ${item.color};"></i>
                        <div class="pmr-item-info">
                            <span class="pmr-item-name">${nombreSeguro}</span>
                            <span class="pmr-item-path">${rutaSegura}</span>
                        </div>
                        <span class="pmr-badge-type" style="background: ${item.badgeBg}; color: ${item.color};">${item.badge}</span>
                    </div>
                `;
            }).join('');

            // Scroll automático para mantener visible el elemento seleccionado
            const itemSeleccionadoEl = listEl.querySelector(`.pmr-item[data-index="${this.indiceSeleccionado}"]`);
            if (itemSeleccionadoEl) {
                itemSeleccionadoEl.scrollIntoView({ block: 'nearest' });
            }
        }

        /** Mueve el cursor de selección arriba o abajo */
        moverSeleccion(delta) {
            const total = this.archivosFiltrados.length;
            if (total === 0) return;
            const maxItems = parseInt(this.config.maxItems, 10) || 12;
            const limite = maxItems > 0 ? Math.min(total, maxItems) : total;

            this.indiceSeleccionado = (this.indiceSeleccionado + delta + limite) % limite;
            this.actualizarListaItems();
        }

        /** Abre el archivo actualmente seleccionado con el teclado */
        abrirItemSeleccionado() {
            if (this.archivosFiltrados.length === 0) return;
            const item = this.archivosFiltrados[this.indiceSeleccionado];
            if (item) {
                this.abrirArchivo(item.path, item.name);
            }
        }

        /** Abre un archivo en el Monaco Editor de Prig y lo registra en recientes */
        async abrirArchivo(path, name) {
            this.registrarArchivoReciente(path, name);
            this.cerrarMenu();

            if (window.editorMgr && typeof window.editorMgr.openFileByPath === 'function') {
                await window.editorMgr.openFileByPath(path, name);
            } else if (window.fileTreeMgr && typeof window.fileTreeMgr.selectFile === 'function') {
                await window.fileTreeMgr.selectFile(path, name);
            } else {
                console.warn('No se encontró editorMgr para abrir:', path);
            }
        }

        /** Abre el modal de configuración de Prig en la pestaña de Editor */
        abrirConfiguracion(e) {
            if (e) e.stopPropagation();
            this.cerrarMenu();
            if (window.globalConfigMgr && typeof window.globalConfigMgr.openModal === 'function') {
                window.globalConfigMgr.openModal('editor');
            }
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

        escaparJs(str) {
            if (!str) return '';
            return String(str).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
        }
    }

    // Instanciar globalmente
    window.MenuRuedaArchivos = MenuRuedaArchivos;
    window.menuRuedaArchivos = new MenuRuedaArchivos();

})();

