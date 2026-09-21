/**
 * GitHub Stats Widget para Prig IDE
 * Permite previsualizar, personalizar y sincronizar la tarjeta de estadísticas
 * de aprendizaje del usuario directamente en su perfil de GitHub (username/username).
 */
(function() {
    'use strict';

    const GitHubWidget = {
        config: {
            tema: 'catppuccin',
            mostrar_racha: true,
            mostrar_desafios: true,
            mostrar_youtube: true,
            mostrar_kaggle: true,
            mostrar_conceptos: true,
            mostrar_modelos: false,
            mostrar_nivel: true,
            ultimo_sync: null
        },
        stats: null,
        svg: '',
        markdown: '',
        usuario: null,
        tieneToken: false,
        cargando: false,

        /**
         * Inicializa o crea el modal en el DOM
         */
        _asegurarModal() {
            let modal = document.getElementById('modal-github-widget');
            if (modal) return modal;

            modal = document.createElement('div');
            modal.id = 'modal-github-widget';
            modal.className = 'modal-overlay';
            modal.style.cssText = `
                display: none;
                position: fixed;
                inset: 0;
                background: rgba(10, 10, 16, 0.85);
                backdrop-filter: blur(8px);
                z-index: 10000;
                justify-content: center;
                align-items: center;
                padding: 20px;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            `;

            modal.innerHTML = `
                <div class="modal-content" style="
                    background: #181825;
                    border: 1px solid #313244;
                    border-radius: 14px;
                    width: 95%;
                    max-width: 1080px;
                    max-height: 92vh;
                    display: flex;
                    flex-direction: column;
                    overflow: hidden;
                    box-shadow: 0 20px 48px rgba(0, 0, 0, 0.7);
                    color: #cdd6f4;
                ">
                    <!-- Modal Header -->
                    <div style="
                        padding: 18px 24px;
                        border-bottom: 1px solid #313244;
                        display: flex;
                        justify-content: space-between;
                        align-items: center;
                        background: rgba(24, 24, 37, 0.6);
                    ">
                        <div style="display: flex; align-items: center; gap: 14px;">
                            <div style="
                                width: 42px;
                                height: 42px;
                                border-radius: 10px;
                                background: linear-gradient(135deg, #89b4fa, #cba6f7);
                                display: flex;
                                align-items: center;
                                justify-content: center;
                                font-size: 22px;
                                color: #11111b;
                                box-shadow: 0 4px 12px rgba(137, 180, 250, 0.3);
                            ">
                                <i class="fa-brands fa-github"></i>
                            </div>
                            <div>
                                <h3 style="margin: 0; font-size: 17px; font-weight: 700; color: #fff; display: flex; align-items: center; gap: 8px;">
                                    Tarjeta de Estadísticas para tu Perfil de GitHub
                                    <span style="font-size: 11px; background: rgba(137, 180, 250, 0.15); color: #89b4fa; padding: 2px 8px; border-radius: 10px; border: 1px solid rgba(137, 180, 250, 0.3);">GitHub Profile</span>
                                </h3>
                                <span style="font-size: 12px; color: #a6adc8;">
                                    Publica automáticamente tus logros de Prig IDE en tu repositorio especial <code>&lt;username&gt;/&lt;username&gt;</code>
                                </span>
                            </div>
                        </div>
                        <button id="ghw-btn-cerrar" style="
                            background: transparent;
                            border: none;
                            color: #a6adc8;
                            font-size: 22px;
                            cursor: pointer;
                            padding: 4px 8px;
                            border-radius: 6px;
                            transition: color 0.15s;
                        " title="Cerrar (Esc)"><i class="fa-solid fa-xmark"></i></button>
                    </div>

                    <!-- Modal Body (2 columnas) -->
                    <div style="flex: 1; overflow-y: auto; padding: 24px; display: grid; grid-template-columns: 360px 1fr; gap: 24px;">
                        
                        <!-- Panel Izquierdo: Controles y Opciones -->
                        <div style="display: flex; flex-direction: column; gap: 18px;">
                            
                            <!-- Estado de Conexión GitHub -->
                            <div id="ghw-auth-box" style="
                                background: #1e1e2e;
                                border: 1px solid #313244;
                                border-radius: 10px;
                                padding: 14px;
                                display: flex;
                                align-items: center;
                                gap: 12px;
                            ">
                                <div id="ghw-auth-avatar" style="
                                    width: 40px;
                                    height: 40px;
                                    border-radius: 50%;
                                    background: #313244;
                                    display: flex;
                                    align-items: center;
                                    justify-content: center;
                                    overflow: hidden;
                                    flex-shrink: 0;
                                ">
                                    <i class="fa-solid fa-user" style="color: #a6adc8;"></i>
                                </div>
                                <div style="flex: 1; min-width: 0;">
                                    <div id="ghw-auth-nombre" style="font-weight: 600; font-size: 13px; color: #fff; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                                        Comprobando GitHub...
                                    </div>
                                    <div id="ghw-auth-estado" style="font-size: 11px; color: #a6adc8;">
                                        Verificando token guardado
                                    </div>
                                </div>
                            </div>

                            <!-- Selector de Temas -->
                            <div style="background: #1e1e2e; border: 1px solid #313244; border-radius: 10px; padding: 14px;">
                                <div style="font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: #a6adc8; margin-bottom: 10px; display: flex; justify-content: space-between;">
                                    <span>Tema Visual</span>
                                    <span id="ghw-tema-nombre" style="color: #89b4fa; text-transform: none; font-weight: 500;">Catppuccin</span>
                                </div>
                                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px;" id="ghw-temas-container">
                                    <button class="ghw-tema-btn" data-tema="catppuccin" style="
                                        background: #181825;
                                        border: 1px solid #89b4fa;
                                        color: #fff;
                                        padding: 8px 10px;
                                        border-radius: 8px;
                                        font-size: 12px;
                                        cursor: pointer;
                                        display: flex;
                                        align-items: center;
                                        gap: 8px;
                                        text-align: left;
                                    ">
                                        <span style="width: 12px; height: 12px; border-radius: 50%; background: #cba6f7; display: inline-block;"></span>
                                        <span>Catppuccin</span>
                                    </button>
                                    <button class="ghw-tema-btn" data-tema="mocha" style="
                                        background: #11111b;
                                        border: 1px solid #313244;
                                        color: #a6adc8;
                                        padding: 8px 10px;
                                        border-radius: 8px;
                                        font-size: 12px;
                                        cursor: pointer;
                                        display: flex;
                                        align-items: center;
                                        gap: 8px;
                                        text-align: left;
                                    ">
                                        <span style="width: 12px; height: 12px; border-radius: 50%; background: #fab387; display: inline-block;"></span>
                                        <span>Mocha Dark</span>
                                    </button>
                                    <button class="ghw-tema-btn" data-tema="cyber" style="
                                        background: #090d16;
                                        border: 1px solid #313244;
                                        color: #a6adc8;
                                        padding: 8px 10px;
                                        border-radius: 8px;
                                        font-size: 12px;
                                        cursor: pointer;
                                        display: flex;
                                        align-items: center;
                                        gap: 8px;
                                        text-align: left;
                                    ">
                                        <span style="width: 12px; height: 12px; border-radius: 50%; background: #00ffcc; display: inline-block;"></span>
                                        <span>Cyber Neon</span>
                                    </button>
                                    <button class="ghw-tema-btn" data-tema="minimal" style="
                                        background: #0d1117;
                                        border: 1px solid #313244;
                                        color: #a6adc8;
                                        padding: 8px 10px;
                                        border-radius: 8px;
                                        font-size: 12px;
                                        cursor: pointer;
                                        display: flex;
                                        align-items: center;
                                        gap: 8px;
                                        text-align: left;
                                    ">
                                        <span style="width: 12px; height: 12px; border-radius: 50%; background: #58a6ff; display: inline-block;"></span>
                                        <span>Minimal</span>
                                    </button>
                                </div>
                            </div>

                            <!-- Métricas Visibles (Toggles) -->
                            <div style="background: #1e1e2e; border: 1px solid #313244; border-radius: 10px; padding: 14px;">
                                <div style="font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: #a6adc8; margin-bottom: 12px;">
                                    Métricas a Mostrar
                                </div>
                                <div style="display: flex; flex-direction: column; gap: 10px; font-size: 13px;">
                                    <label style="display: flex; align-items: center; gap: 10px; cursor: pointer;">
                                        <input type="checkbox" id="ghw-opt-racha" checked style="accent-color: #fab387; width: 16px; height: 16px;">
                                        <span><i class="fa-solid fa-fire" style="color: #fab387; width: 16px;"></i> Racha y días activos</span>
                                    </label>
                                    <label style="display: flex; align-items: center; gap: 10px; cursor: pointer;">
                                        <input type="checkbox" id="ghw-opt-desafios" checked style="accent-color: #cba6f7; width: 16px; height: 16px;">
                                        <span><i class="fa-solid fa-code" style="color: #cba6f7; width: 16px;"></i> Desafíos (Python & C++)</span>
                                    </label>
                                    <label style="display: flex; align-items: center; gap: 10px; cursor: pointer;">
                                        <input type="checkbox" id="ghw-opt-youtube" checked style="accent-color: #f38ba8; width: 16px; height: 16px;">
                                        <span><i class="fa-brands fa-youtube" style="color: #f38ba8; width: 16px;"></i> Cursos y notas de YouTube</span>
                                    </label>
                                    <label style="display: flex; align-items: center; gap: 10px; cursor: pointer;">
                                        <input type="checkbox" id="ghw-opt-kaggle" checked style="accent-color: #89b4fa; width: 16px; height: 16px;">
                                        <span><i class="fa-brands fa-kaggle" style="color: #89b4fa; width: 16px;"></i> Celdas y lecturas de Kaggle</span>
                                    </label>
                                    <label style="display: flex; align-items: center; gap: 10px; cursor: pointer;">
                                        <input type="checkbox" id="ghw-opt-conceptos" checked style="accent-color: #a6e3a1; width: 16px; height: 16px;">
                                        <span><i class="fa-solid fa-brain" style="color: #a6e3a1; width: 16px;"></i> Conceptos clave dominados</span>
                                    </label>
                                    <label style="display: flex; align-items: center; gap: 10px; cursor: pointer;">
                                        <input type="checkbox" id="ghw-opt-nivel" checked style="accent-color: #89b4fa; width: 16px; height: 16px;">
                                        <span><i class="fa-solid fa-graduation-cap" style="color: #89b4fa; width: 16px;"></i> Nivel de programación</span>
                                    </label>
                                    <label style="display: flex; align-items: center; gap: 10px; cursor: pointer;">
                                        <input type="checkbox" id="ghw-opt-modelos" style="accent-color: #b4befe; width: 16px; height: 16px;">
                                        <span><i class="fa-solid fa-microchip" style="color: #b4befe; width: 16px;"></i> Modelo IA local en uso</span>
                                    </label>
                                </div>
                            </div>

                            <!-- Acciones de Sincronización -->
                            <div style="display: flex; flex-direction: column; gap: 10px;">
                                <button id="ghw-btn-publicar" style="
                                    background: linear-gradient(135deg, #89b4fa, #cba6f7);
                                    color: #11111b;
                                    font-weight: 700;
                                    font-size: 14px;
                                    border: none;
                                    padding: 12px 18px;
                                    border-radius: 10px;
                                    cursor: pointer;
                                    display: flex;
                                    align-items: center;
                                    justify-content: center;
                                    gap: 10px;
                                    box-shadow: 0 4px 14px rgba(137, 180, 250, 0.35);
                                    transition: transform 0.1s, filter 0.2s;
                                ">
                                    <i class="fa-solid fa-rocket"></i> Sincronizar con GitHub Profile
                                </button>

                                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px;">
                                    <button id="ghw-btn-copiar-md" style="
                                        background: #1e1e2e;
                                        border: 1px solid #313244;
                                        color: #cdd6f4;
                                        padding: 8px 12px;
                                        border-radius: 8px;
                                        font-size: 12px;
                                        cursor: pointer;
                                        display: flex;
                                        align-items: center;
                                        justify-content: center;
                                        gap: 6px;
                                    ">
                                        <i class="fa-regular fa-clipboard"></i> Copiar Markdown
                                    </button>
                                    <button id="ghw-btn-descargar-svg" style="
                                        background: #1e1e2e;
                                        border: 1px solid #313244;
                                        color: #cdd6f4;
                                        padding: 8px 12px;
                                        border-radius: 8px;
                                        font-size: 12px;
                                        cursor: pointer;
                                        display: flex;
                                        align-items: center;
                                        justify-content: center;
                                        gap: 6px;
                                    ">
                                        <i class="fa-solid fa-download"></i> Descargar SVG
                                    </button>
                                </div>
                            </div>

                        </div>

                        <!-- Panel Derecho: Vista Previa en Vivo y Estado -->
                        <div style="display: flex; flex-direction: column; gap: 18px;">
                            
                            <!-- Estado / Mensaje de Alerta -->
                            <div id="ghw-mensaje" style="display: none; padding: 12px 16px; border-radius: 8px; font-size: 13px; line-height: 1.4;"></div>

                            <!-- Contenedor del SVG -->
                            <div style="
                                background: #11111b;
                                border: 1px solid #313244;
                                border-radius: 12px;
                                padding: 20px;
                                display: flex;
                                flex-direction: column;
                                align-items: center;
                                justify-content: center;
                                position: relative;
                                min-height: 290px;
                            ">
                                <div style="
                                    width: 100%;
                                    display: flex;
                                    justify-content: space-between;
                                    align-items: center;
                                    margin-bottom: 12px;
                                    font-size: 11px;
                                    color: #a6adc8;
                                ">
                                    <span style="display: flex; align-items: center; gap: 6px;">
                                        <i class="fa-solid fa-eye" style="color: #89b4fa;"></i> Vista Previa en Tiempo Real
                                    </span>
                                    <span id="ghw-sync-status">No sincronizado aún</span>
                                </div>

                                <div id="ghw-svg-container" style="
                                    width: 100%;
                                    max-width: 530px;
                                    display: flex;
                                    justify-content: center;
                                    align-items: center;
                                    transition: opacity 0.2s;
                                ">
                                    <div style="color: #a6adc8; font-size: 13px;">Generando vista previa...</div>
                                </div>
                            </div>

                            <!-- Bloque Markdown & Explicación -->
                            <div style="background: #1e1e2e; border: 1px solid #313244; border-radius: 10px; padding: 16px;">
                                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                                    <div style="font-size: 12px; font-weight: 600; color: #cdd6f4;">
                                        <i class="fa-brands fa-markdown" style="color: #89b4fa; margin-right: 6px;"></i> Código Markdown para tu README
                                    </div>
                                    <button id="ghw-btn-copiar-snippet" style="
                                        background: transparent;
                                        border: none;
                                        color: #89b4fa;
                                        font-size: 12px;
                                        cursor: pointer;
                                        display: flex;
                                        align-items: center;
                                        gap: 4px;
                                    "><i class="fa-regular fa-copy"></i> Copiar</button>
                                </div>
                                <pre id="ghw-md-snippet" style="
                                    background: #11111b;
                                    border: 1px solid #313244;
                                    border-radius: 6px;
                                    padding: 10px 12px;
                                    font-family: monospace;
                                    font-size: 11px;
                                    color: #a6e3a1;
                                    overflow-x: auto;
                                    white-space: pre-wrap;
                                    word-break: break-all;
                                    margin: 0;
                                ">Cargando snippet...</pre>
                                <div style="font-size: 11px; color: #a6adc8; margin-top: 10px; line-height: 1.4;">
                                    <i class="fa-solid fa-circle-info" style="color: #89b4fa;"></i> 
                                    <b>Sincronización Segura:</b> Al hacer clic en <b>Sincronizar</b>, Prig inyectará la tarjeta dentro de las etiquetas 
                                    <code>&lt;!-- PRIG-STATS:START --&gt;</code> y <code>&lt;!-- PRIG-STATS:END --&gt;</code> en el <code>README.md</code> de tu repositorio personal, preservando intacto todo tu texto, biografía y enlaces existentes.
                                </div>
                            </div>

                        </div>
                    </div>
                </div>
            `;

            document.body.appendChild(modal);

            // Escuchar eventos de cierre
            modal.querySelector('#ghw-btn-cerrar').addEventListener('click', () => this.cerrar());
            modal.addEventListener('click', (e) => {
                if (e.target === modal) this.cerrar();
            });

            // Selector de temas
            modal.querySelectorAll('.ghw-tema-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const tema = btn.getAttribute('data-tema');
                    this.cambiarTema(tema);
                });
            });

            // Toggles
            const bindToggle = (id, key) => {
                const el = modal.querySelector('#' + id);
                if (el) {
                    el.addEventListener('change', () => {
                        this.config[key] = el.checked;
                        this.actualizarPreview();
                    });
                }
            };
            bindToggle('ghw-opt-racha', 'mostrar_racha');
            bindToggle('ghw-opt-desafios', 'mostrar_desafios');
            bindToggle('ghw-opt-youtube', 'mostrar_youtube');
            bindToggle('ghw-opt-kaggle', 'mostrar_kaggle');
            bindToggle('ghw-opt-conceptos', 'mostrar_conceptos');
            bindToggle('ghw-opt-nivel', 'mostrar_nivel');
            bindToggle('ghw-opt-modelos', 'mostrar_modelos');

            // Botones de acción
            modal.querySelector('#ghw-btn-publicar').addEventListener('click', () => this.publicar());
            modal.querySelector('#ghw-btn-copiar-md').addEventListener('click', () => this.copiarMarkdown());
            modal.querySelector('#ghw-btn-copiar-snippet').addEventListener('click', () => this.copiarMarkdown());
            modal.querySelector('#ghw-btn-descargar-svg').addEventListener('click', () => this.descargarSVG());

            return modal;
        },

        /**
         * Recolecta métricas adicionales del cliente (YouTube notas/frames, etc.)
         */
        _obtenerExtrasCliente() {
            let ytCursos = 0, ytHoras = 0, ytFotogramas = 0, ytNotas = 0;
            try {
                if (window.YouTubeHub && typeof window.YouTubeHub.obtenerResumenNotas === 'function') {
                    const resYT = window.YouTubeHub.obtenerResumenNotas();
                    ytNotas = resYT.totalNotas || 0;
                    ytFotogramas = resYT.totalFotogramas || 0;
                    ytCursos = resYT.cursosCompletados || 0;
                } else {
                    // Fallback a localStorage
                    const rawNotas = localStorage.getItem('prig_youtube_visual_notes_v1');
                    if (rawNotas) {
                        const parsed = JSON.parse(rawNotas);
                        ytNotas = Object.keys(parsed).length;
                        ytFotogramas = Object.values(parsed).filter(n => n.tipo === 'frame' || n.imagen).length;
                    }
                }
            } catch (e) {
                console.warn('Error leyendo notas locales de YouTube:', e);
            }

            // Modelo local en uso
            let modeloLocal = 'Qwen 2.5 Coder';
            try {
                if (window.AIEngine && window.AIEngine.currentModel) {
                    modeloLocal = window.AIEngine.currentModel;
                }
            } catch (e) {}

            return {
                yt_cursos_completados: ytCursos,
                yt_horas: ytHoras,
                yt_fotogramas: ytFotogramas,
                yt_notas: ytNotas,
                modelo_local: modeloLocal
            };
        },

        /**
         * Abre el modal y carga configuración y vista previa
         */
        async abrir() {
            const modal = this._asegurarModal();
            modal.style.display = 'flex';
            this.ocultarMensaje();

            try {
                // 1. Cargar configuración y datos de usuario
                const resCfg = await fetch('/api/github/widget/config');
                if (resCfg.ok) {
                    const dataCfg = await resCfg.json();
                    if (dataCfg.config) {
                        this.config = Object.assign(this.config, dataCfg.config);
                    }
                    this.tieneToken = !!dataCfg.tiene_token;
                    this.usuario = dataCfg.usuario;
                    this._renderUsuario();
                    this._actualizarUIConfig();
                }
            } catch (e) {
                console.error('Error al cargar config de widget GitHub:', e);
            }

            // 2. Generar y mostrar vista previa
            await this.actualizarPreview();
        },

        cerrar() {
            const modal = document.getElementById('modal-github-widget');
            if (modal) modal.style.display = 'none';
        },

        _renderUsuario() {
            const avatar = document.getElementById('ghw-auth-avatar');
            const nombre = document.getElementById('ghw-auth-nombre');
            const estado = document.getElementById('ghw-auth-estado');
            const btnPublicar = document.getElementById('ghw-btn-publicar');

            if (this.tieneToken && this.usuario) {
                if (avatar) {
                    if (this.usuario.avatar_url) {
                        avatar.innerHTML = `<img src="${this.usuario.avatar_url}" style="width:100%; height:100%; border-radius:50%; object-fit:cover;">`;
                    } else {
                        avatar.innerHTML = `<i class="fa-brands fa-github" style="color:#89b4fa; font-size:20px;"></i>`;
                    }
                }
                if (nombre) {
                    nombre.innerHTML = `<a href="${this.usuario.html_url || '#'}" target="_blank" style="color:#fff; text-decoration:none; display:flex; align-items:center; gap:6px;">${this.usuario.name || this.usuario.login} <span style="color:#89b4fa; font-size:11px;">@${this.usuario.login}</span></a>`;
                }
                if (estado) {
                    estado.innerHTML = `<span style="color:#a6e3a1;"><i class="fa-solid fa-circle-check"></i> Conectado a GitHub</span> · Repositorio: <code>${this.usuario.login}/${this.usuario.login}</code>`;
                }
                if (btnPublicar) {
                    btnPublicar.disabled = false;
                    btnPublicar.style.opacity = '1';
                    btnPublicar.style.cursor = 'pointer';
                }
            } else if (this.tieneToken) {
                if (avatar) avatar.innerHTML = `<i class="fa-brands fa-github" style="color:#89b4fa; font-size:20px;"></i>`;
                if (nombre) nombre.innerText = 'Token de GitHub configurado';
                if (estado) estado.innerHTML = `<span style="color:#a6e3a1;">Listo para sincronizar</span>`;
                if (btnPublicar) {
                    btnPublicar.disabled = false;
                    btnPublicar.style.opacity = '1';
                    btnPublicar.style.cursor = 'pointer';
                }
            } else {
                if (avatar) avatar.innerHTML = `<i class="fa-solid fa-triangle-exclamation" style="color:#fab387; font-size:18px;"></i>`;
                if (nombre) nombre.innerText = 'Sin cuenta de GitHub conectada';
                if (estado) {
                    estado.innerHTML = `<span style="color:#fab387;">Agrega tu token en la sección GitHub</span>`;
                }
                if (btnPublicar) {
                    btnPublicar.title = 'Configura tu token de GitHub para publicar directamente';
                }
            }
        },

        _actualizarUIConfig() {
            // Checkboxes
            const setCheck = (id, val) => {
                const el = document.getElementById(id);
                if (el) el.checked = !!val;
            };
            setCheck('ghw-opt-racha', this.config.mostrar_racha);
            setCheck('ghw-opt-desafios', this.config.mostrar_desafios);
            setCheck('ghw-opt-youtube', this.config.mostrar_youtube);
            setCheck('ghw-opt-kaggle', this.config.mostrar_kaggle);
            setCheck('ghw-opt-conceptos', this.config.mostrar_conceptos);
            setCheck('ghw-opt-nivel', this.config.mostrar_nivel);
            setCheck('ghw-opt-modelos', this.config.mostrar_modelos);

            // Botones de temas
            document.querySelectorAll('.ghw-tema-btn').forEach(btn => {
                const t = btn.getAttribute('data-tema');
                if (t === this.config.tema) {
                    btn.style.borderColor = '#89b4fa';
                    btn.style.boxShadow = '0 0 10px rgba(137, 180, 250, 0.25)';
                } else {
                    btn.style.borderColor = '#313244';
                    btn.style.boxShadow = 'none';
                }
            });

            // Nombre del tema
            const nombresTemas = {
                catppuccin: 'Catppuccin Macchiato',
                mocha: 'Mocha Dark',
                cyber: 'Cyber Neon',
                minimal: 'Minimal Monocromo'
            };
            const lblTema = document.getElementById('ghw-tema-nombre');
            if (lblTema) lblTema.innerText = nombresTemas[this.config.tema] || this.config.tema;

            // Último sync
            const statusEl = document.getElementById('ghw-sync-status');
            if (statusEl) {
                if (this.config.ultimo_sync) {
                    statusEl.innerHTML = `<span style="color:#a6e3a1;"><i class="fa-solid fa-clock-rotate-left"></i> Último commit: ${this.config.ultimo_sync}</span>`;
                } else {
                    statusEl.innerText = 'No sincronizado aún';
                }
            }
        },

        cambiarTema(tema) {
            this.config.tema = tema;
            this._actualizarUIConfig();
            this.actualizarPreview();
        },

        async actualizarPreview() {
            const container = document.getElementById('ghw-svg-container');
            const mdSnippet = document.getElementById('ghw-md-snippet');
            if (container) container.style.opacity = '0.5';

            try {
                const res = await fetch('/api/github/widget/preview', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        config: this.config,
                        extras: this._obtenerExtrasCliente()
                    })
                });

                if (res.ok) {
                    const data = await res.json();
                    this.svg = data.svg;
                    this.markdown = data.markdown;
                    this.stats = data.stats;

                    if (container) {
                        container.innerHTML = data.svg;
                        // Ajustar el SVG para que sea responsive dentro del contenedor
                        const svgEl = container.querySelector('svg');
                        if (svgEl) {
                            svgEl.style.width = '100%';
                            svgEl.style.height = 'auto';
                            svgEl.style.maxHeight = '280px';
                        }
                    }

                    if (mdSnippet) {
                        mdSnippet.innerText = data.markdown;
                    }
                } else {
                    throw new Error('Error al generar preview en el backend');
                }
            } catch (err) {
                console.error('Error al actualizar preview del widget:', err);
                if (container) {
                    container.innerHTML = `<div style="color:#f38ba8; font-size:13px;"><i class="fa-solid fa-triangle-exclamation"></i> Error al generar SVG: ${err.message}</div>`;
                }
            } finally {
                if (container) container.style.opacity = '1';
            }
        },

        async publicar() {
            const btn = document.getElementById('ghw-btn-publicar');
            const textoOriginal = btn ? btn.innerHTML : '';
            this.ocultarMensaje();

            if (btn) {
                btn.disabled = true;
                btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Sincronizando con GitHub...`;
            }

            try {
                const res = await fetch('/api/github/widget/publicar', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        config: this.config,
                        extras: this._obtenerExtrasCliente()
                    })
                });

                const data = await res.json();
                if (!res.ok) {
                    throw new Error(data.detail || data.mensaje || 'Error desconocido al sincronizar');
                }

                this.mostrarMensaje('exito', `
                    <div style="font-weight:600; margin-bottom:4px;"><i class="fa-solid fa-circle-check"></i> ¡Publicado exitosamente en GitHub!</div>
                    <div style="font-size:12px;">Se actualizaron <code>prig-stats.svg</code> y <code>README.md</code> en tu perfil <b>${data.repo}</b>.</div>
                    ${data.url_commit ? `<div style="margin-top:6px;"><a href="${data.url_commit}" target="_blank" style="color:#89b4fa; text-decoration:underline;">Ver commit en GitHub <i class="fa-solid fa-arrow-up-right-from-square" style="font-size:10px;"></i></a></div>` : ''}
                `);

                this.config.ultimo_sync = new Date().toLocaleString();
                this._actualizarUIConfig();

            } catch (err) {
                console.error('Error publicando widget en GitHub:', err);
                this.mostrarMensaje('error', `
                    <div style="font-weight:600; margin-bottom:4px;"><i class="fa-solid fa-triangle-exclamation"></i> No se pudo sincronizar</div>
                    <div style="font-size:12px;">${err.message}</div>
                    <div style="font-size:11px; margin-top:6px; color:#a6adc8;">Asegúrate de que tu Personal Access Token tenga los permisos <code>repo</code> y <code>workflow</code> marcados.</div>
                `);
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = textoOriginal;
                }
            }
        },

        copiarMarkdown() {
            if (!this.markdown) return;
            navigator.clipboard.writeText(this.markdown).then(() => {
                this.mostrarMensaje('info', '¡Markdown copiado al portapapeles! Puedes pegarlo en cualquier parte de tu README.');
                setTimeout(() => this.ocultarMensaje(), 4000);
            }).catch(() => {
                this.mostrarMensaje('error', 'No se pudo copiar automáticamente. Por favor selecciónalo y cópialo manualmente.');
            });
        },

        descargarSVG() {
            if (!this.svg) return;
            const blob = new Blob([this.svg], { type: 'image/svg+xml;charset=utf-8' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'prig-stats.svg';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        },

        mostrarMensaje(tipo, html) {
            const el = document.getElementById('ghw-mensaje');
            if (!el) return;
            el.style.display = 'block';
            if (tipo === 'exito') {
                el.style.background = 'rgba(166, 227, 161, 0.12)';
                el.style.border = '1px solid #a6e3a1';
                el.style.color = '#a6e3a1';
            } else if (tipo === 'error') {
                el.style.background = 'rgba(243, 139, 168, 0.12)';
                el.style.border = '1px solid #f38ba8';
                el.style.color = '#f38ba8';
            } else {
                el.style.background = 'rgba(137, 180, 250, 0.12)';
                el.style.border = '1px solid #89b4fa';
                el.style.color = '#89b4fa';
            }
            el.innerHTML = html;
        },

        ocultarMensaje() {
            const el = document.getElementById('ghw-mensaje');
            if (el) el.style.display = 'none';
        }
    };

    // Exportar al objeto global
    window.GitHubWidget = GitHubWidget;

    // Conectar atajo de teclado ESC
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            const m = document.getElementById('modal-github-widget');
            if (m && m.style.display !== 'none') {
                GitHubWidget.cerrar();
            }
        }
    });

})();
