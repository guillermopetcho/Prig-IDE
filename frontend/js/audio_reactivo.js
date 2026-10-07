/**
 * Gestor de Efectos Visuales y Modulación de Luz Reactivos al Audio para Prig IDE.
 * 
 * Permite capturar la salida de audio de la computadora (audio del sistema, pestañas, Spotify,
 * YouTube, VLC o micrófono) mediante:
 * 1. Monitor Nativo de Linux (WebSocket + PipeWire / PulseAudio con selector de apps y pestañas).
 * 2. Web Audio API local (como respaldo).
 * 
 * Modula:
 * 1. Resplandor neón en los bordes, barras y paneles del IDE.
 * 2. Velocidad, tamaño, brillo y destellos del motor de fondos dinámicos (motor_movimiento.js).
 * 3. Pulso y brillo de sintaxis en el editor de código.
 * 4. Ecualizador y espectrograma interactivo en la pestaña de configuración.
 */

class AudioReactivoManager {
    constructor() {
        this.ctxAudio = null;
        this.analyser = null;
        this.sourceNode = null;
        this.gainNode = null;
        this.stream = null;
        this._animFrameId = null;

        // WebSocket para captura nativa directa de Linux
        this._ws = null;
        this._modoCaptura = 'nativo'; // 'nativo' | 'web'
        this._fuenteNativaId = 'sistema_global';
        this._aplicacionesNativas = [];
        this._spectrumNativo = new Array(32).fill(0);

        // Búferes de análisis FFT
        this._dataArray = null;
        this._bufferLength = 0;

        // Estado en vivo
        this._activo = false;
        this._fuenteActual = 'ninguna'; // 'sistema_global' | 'microfono' | ID de app | 'ninguna'
        this._nombreFuenteActual = 'Inactivo';
        this._energiaSuavizada = 0;
        this._bassSuavizado = 0;
        this._midsSuavizado = 0;
        this._trebleSuavizado = 0;

        // Visualizadores canvas registrados
        this._visualizadores = new Set();

        // Configuración por defecto
        this.config = {
            habilitado: false,
            fuentePreferida: 'sistema_global',
            bandaFrecuencia: 'graves',     // 'graves' | 'medios' | 'agudos' | 'completo' | 'personalizado'
            minHz: 20,                     // Para banda personalizada
            maxHz: 250,                    // Para banda personalizada
            sensibilidad: 1.5,             // Multiplicador de ganancia (0.5x - 3.5x)
            umbral: 0.05,                  // Umbral de ruido mínimo (0.0 - 0.4)
            suavizado: 0.82,               // Inercia FFT (0.1 - 0.95)
            
            // Efectos de Luz activables
            efectoBordes: true,            // Pulso neón en bordes y divisiones del IDE
            efectoFondo: true,             // Aceleración y expansión de partículas/ondas en el fondo
            efectoTopbar: true,            // Resplandor en barra superior y pestañas
            efectoSintaxis: false,         // Pulso en palabras clave y funciones del editor
            
            // Color de la luz
            tipoColor: 'tema',             // 'tema' (sigue el acento del tema) o 'personalizado'
            colorLuz: '#00f0ff',           // Color HEX para la luz reactiva
            intensidadLuz: 1.2             // Multiplicador de brillo (0.2x - 3.0x)
        };

        this._estiloDinamico = null;

        // Cargar configuración guardada
        this._cargarConfig();
        this.sincronizarBackend();
    }

    _cargarConfig() {
        try {
            const guardado = localStorage.getItem('prig_audio_reactivo');
            if (guardado) {
                const parsed = JSON.parse(guardado);
                this.config = { ...this.config, ...parsed };
            }
        } catch (e) {
            console.warn('[AudioReactivo] Error al cargar configuración de localStorage:', e);
        }
    }

    async sincronizarBackend() {
        try {
            const res = await fetch('/api/config/audio_reactivo');
            if (res.ok) {
                const data = await res.json();
                if (data && typeof data === 'object' && Object.keys(data).length > 0) {
                    this.config = { ...this.config, ...data };
                    try {
                        localStorage.setItem('prig_audio_reactivo', JSON.stringify(this.config));
                    } catch (e) {}
                    this._actualizarEstilosCss();
                }
            }
        } catch (e) {
            // Backend opcional
        }
    }

    async guardarConfig(nuevaConfig = {}) {
        this.config = { ...this.config, ...nuevaConfig };
        try {
            localStorage.setItem('prig_audio_reactivo', JSON.stringify(this.config));
        } catch (e) {}

        if (this.analyser && typeof this.config.suavizado === 'number') {
            this.analyser.smoothingTimeConstant = Math.max(0.1, Math.min(0.95, this.config.suavizado));
        }

        if (this.gainNode && typeof this.config.sensibilidad === 'number') {
            this.gainNode.gain.value = Math.max(0.5, this.config.sensibilidad * 1.5);
        }

        this._actualizarEstilosCss();

        try {
            await fetch('/api/config/audio_reactivo', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(this.config)
            });
        } catch (e) {
            console.warn('[AudioReactivo] No se pudo persistir en backend:', e);
        }
    }

    /**
     * Obtiene la lista en tiempo real de aplicaciones y pestañas que reproducen audio en el sistema.
     */
    async listarAplicacionesNativas() {
        try {
            const res = await fetch('/api/audio/aplicaciones');
            if (res.ok) {
                const data = await res.json();
                this._aplicacionesNativas = data.aplicaciones || [];
                return this._aplicacionesNativas;
            }
        } catch (e) {
            console.warn('[AudioReactivo] Error consultando aplicaciones al backend:', e);
        }
        return [];
    }

    /**
     * Inicia la captura nativa directa de Linux mediante WebSocket y PipeWire/PulseAudio.
     * @param {string} fuenteId - 'sistema_global' o ID del stream de la aplicación (ej: '305')
     */
    async iniciarCapturaNativa(fuenteId = 'sistema_global', nombreFuente = '') {
        this.detenerCaptura(false);

        this._modoCaptura = 'nativo';
        this._fuenteNativaId = fuenteId || 'sistema_global';
        this._fuenteActual = this._fuenteNativaId;
        this._nombreFuenteActual = nombreFuente || (fuenteId === 'sistema_global' ? 'Todo el Audio de la PC' : `Aplicación #${fuenteId}`);

        try {
            // Notificar al backend la fuente elegida
            await fetch('/api/audio/seleccionar_fuente', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ fuente_id: this._fuenteNativaId })
            });
        } catch (e) {
            console.warn('[AudioReactivo] Error notificando fuente al backend:', e);
        }

        let host = window.location.host;
        if (!host || host === '' || host === 'null') {
            host = '127.0.0.1:8000';
        }
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${host}/ws/audio_reactivo`;

        console.log(`[AudioReactivo] Conectando WebSocket de audio a ${wsUrl}...`);

        return new Promise((resolve) => {
            let resuelto = false;

            const activarFallbackHttp = () => {
                if (this._pollingInterval) clearInterval(this._pollingInterval);
                console.log('[AudioReactivo] Usando canal HTTP de alta frecuencia como respaldo.');
                this._activo = true;
                this.config.habilitado = true;
                this.guardarConfig();
                document.documentElement.setAttribute('data-audio-active', '1');
                this._actualizarEstilosCss();
                this._notificarCambioEstado('conectado');

                this._pollingInterval = setInterval(async () => {
                    if (!this._activo) return;
                    try {
                        const res = await fetch('/api/audio/datos_actuales');
                        if (res.ok) {
                            const data = await res.json();
                            this._procesarPaqueteAudio(data);
                        }
                    } catch (e) {}
                }, 25); // ~40 FPS

                if (!resuelto) {
                    resuelto = true;
                    resolve({ ok: true, fuente: this._fuenteNativaId });
                }
            };

            const timeoutId = setTimeout(() => {
                if (!resuelto) {
                    activarFallbackHttp();
                }
            }, 1800);

            try {
                this._ws = new WebSocket(wsUrl);

                this._ws.onopen = () => {
                    if (!resuelto) {
                        resuelto = true;
                        clearTimeout(timeoutId);
                    }
                    console.log('[AudioReactivo] Conexión nativa WebSocket de audio activa (60 FPS).');
                    this._activo = true;
                    this.config.habilitado = true;
                    this.guardarConfig();
                    document.documentElement.setAttribute('data-audio-active', '1');
                    this._actualizarEstilosCss();
                    this._notificarCambioEstado('conectado');
                    resolve({ ok: true, fuente: this._fuenteNativaId });
                };

                this._ws.onmessage = (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        this._procesarPaqueteAudio(data);
                    } catch (err) {}
                };

                this._ws.onclose = () => {
                    if (this._modoCaptura === 'nativo' && this._activo) {
                        activarFallbackHttp();
                    }
                };

                this._ws.onerror = (err) => {
                    console.warn('[AudioReactivo] WebSocket nativo no disponible, activando canal directo HTTP:', err);
                    clearTimeout(timeoutId);
                    activarFallbackHttp();
                };

            } catch (err) {
                clearTimeout(timeoutId);
                activarFallbackHttp();
            }
        });
    }

    _procesarPaqueteAudio(data) {
        if (!data) return;

        const sens = Math.max(0.5, this.config.sensibilidad || 1.5);
        const umbral = this.config.umbral || 0.05;

        const bass = Math.min(1.0, Math.max(0, (data.bass || 0) - umbral) * sens);
        const mids = Math.min(1.0, Math.max(0, (data.mids || 0) - umbral) * sens);
        const treble = Math.min(1.0, Math.max(0, (data.treble || 0) - umbral) * sens);
        const energy = Math.min(1.0, Math.max(0, (data.energy || 0) - umbral) * sens);

        // Seleccionar energía según la banda elegida
        let targetE = energy;
        const b = this.config.bandaFrecuencia || 'graves';
        if (b === 'graves') targetE = bass;
        else if (b === 'medios') targetE = mids;
        else if (b === 'agudos') targetE = treble;
        else if (b === 'completo') targetE = energy;

        // Suavizado exponencial reactivo
        const decay = 0.38;
        this._energiaSuavizada += (targetE - this._energiaSuavizada) * decay;
        this._bassSuavizado += (bass - this._bassSuavizado) * decay;
        this._midsSuavizado += (mids - this._midsSuavizado) * decay;
        this._trebleSuavizado += (treble - this._trebleSuavizado) * decay;

        // Espectro de 32 bandas
        if (Array.isArray(data.spectrum)) {
            this._spectrumNativo = data.spectrum.map(v => Math.min(1.0, Math.max(0, v * sens)));
        }

        // Inyectar variables CSS y dibujar visualizadores
        this._inyectarVariablesCss();
        if (this._visualizadores.size > 0) {
            this._renderizarVisualizadoresNativos();
        }
    }

    /**
     * Detiene la captura de audio y limpia los recursos.
     */
    detenerCaptura(notificar = true) {
        if (this._pollingInterval) {
            clearInterval(this._pollingInterval);
            this._pollingInterval = null;
        }

        if (this._ws) {
            try { this._ws.close(); } catch (e) {}
            this._ws = null;
        }

        if (this._animFrameId) {
            cancelAnimationFrame(this._animFrameId);
            this._animFrameId = null;
        }

        if (this.gainNode) {
            try { this.gainNode.disconnect(); } catch (e) {}
            this.gainNode = null;
        }

        if (this.sourceNode) {
            try { this.sourceNode.disconnect(); } catch (e) {}
            this.sourceNode = null;
        }

        if (this.stream) {
            try {
                this.stream.getTracks().forEach(t => t.stop());
            } catch (e) {}
            this.stream = null;
        }

        this._activo = false;
        this._fuenteActual = 'ninguna';
        this._nombreFuenteActual = 'Inactivo';
        this._energiaSuavizada = 0;
        this._bassSuavizado = 0;
        this._midsSuavizado = 0;
        this._trebleSuavizado = 0;
        this._spectrumNativo.fill(0);

        this._resetearVariablesCss();

        if (notificar) {
            this._notificarCambioEstado('desconectado');
        }
    }

    estaActivo() {
        return this._activo;
    }

    getFuenteActual() {
        return this._fuenteActual;
    }

    getNombreFuenteActual() {
        return this._nombreFuenteActual;
    }

    obtenerColorLuz() {
        if (this.config.tipoColor === 'personalizado' && this.config.colorLuz) {
            return this.config.colorLuz;
        }
        if (window.aparienciaMgr && window.aparienciaMgr.estado) {
            return window.aparienciaMgr.estado.acento || '#00f0ff';
        }
        return '#00f0ff';
    }

    conectarVisualizadorCanvas(canvas) {
        if (!canvas) return;
        this._visualizadores.add(canvas);
    }

    desconectarVisualizadorCanvas(canvas) {
        this._visualizadores.delete(canvas);
    }

    getFactoresMovimiento() {
        if (!this._activo || !this.config.efectoFondo) {
            return {
                reactivo: false,
                energia: 0,
                energiaBass: 0,
                energiaTreble: 0,
                boostVelocidad: 1.0,
                boostTamano: 1.0,
                boostBrillo: 1.0,
                colorLuz: this.obtenerColorLuz()
            };
        }

        const intensidad = Math.max(0.2, Math.min(3.0, this.config.intensidadLuz || 1.0));
        const e = this._energiaSuavizada;
        const b = this._bassSuavizado;
        const t = this._trebleSuavizado;

        return {
            reactivo: true,
            energia: e,
            energiaBass: b,
            energiaTreble: t,
            boostVelocidad: 1.0 + (e * 2.4 * intensidad),
            boostTamano: 1.0 + (b * 2.0 * intensidad),
            boostBrillo: 1.0 + (e * 1.8 * intensidad),
            colorLuz: this.obtenerColorLuz()
        };
    }

    _inyectarVariablesCss() {
        const root = document.documentElement;
        const color = this.obtenerColorLuz();
        const intensidad = Math.max(0.2, Math.min(3.0, this.config.intensidadLuz || 1.2));
        const e = this._energiaSuavizada;
        const b = this._bassSuavizado;
        const t = this._trebleSuavizado;

        const hexToRgba = (hex, a) => {
            let c = (hex || '#00f0ff').replace('#', '');
            if (c.length === 3) c = c.split('').map(x => x + x).join('');
            const num = parseInt(c, 16);
            if (isNaN(num)) return `rgba(0, 240, 255, ${a})`;
            return `rgba(${(num >> 16) & 255}, ${(num >> 8) & 255}, ${num & 255}, ${a})`;
        };

        const glowRadius = Math.max(0, Math.round(e * 34 * intensidad));
        const outerAlpha = Math.min(1.0, e * 0.95 * intensidad);
        const innerAlpha = Math.min(0.7, e * 0.5 * intensidad);
        const borderAlpha = Math.min(1.0, 0.25 + (e * 0.75 * intensidad));

        const glowColorOuter = hexToRgba(color, outerAlpha.toFixed(2));
        const glowColorInner = hexToRgba(color, innerAlpha.toFixed(2));
        const borderColor = hexToRgba(color, borderAlpha.toFixed(2));

        root.style.setProperty('--audio-energy', e.toFixed(3));
        root.style.setProperty('--audio-bass', b.toFixed(3));
        root.style.setProperty('--audio-treble', t.toFixed(3));
        root.style.setProperty('--audio-color', color);
        root.style.setProperty('--audio-glow-shadow', `0 0 ${glowRadius}px ${glowColorOuter}, inset 0 0 ${Math.round(glowRadius * 0.4)}px ${glowColorInner}`);
        root.style.setProperty('--audio-glow-topbar', `0 3px ${glowRadius + 6}px ${glowColorOuter}`);
        root.style.setProperty('--audio-border-color', borderColor);
        root.style.setProperty('--audio-text-glow', `0 0 ${Math.round(glowRadius * 0.6)}px ${color}`);
        root.style.setProperty('--audio-scale', (1.0 + (b * 0.025 * intensidad)).toFixed(3));
        root.style.setProperty('--audio-active', '1');
    }

    _resetearVariablesCss() {
        const root = document.documentElement;
        root.style.setProperty('--audio-energy', '0');
        root.style.setProperty('--audio-bass', '0');
        root.style.setProperty('--audio-treble', '0');
        root.style.setProperty('--audio-glow-shadow', 'none');
        root.style.setProperty('--audio-glow-topbar', 'none');
        root.style.setProperty('--audio-border-color', 'var(--border-color)');
        root.style.setProperty('--audio-text-glow', 'none');
        root.style.setProperty('--audio-scale', '1');
        root.style.setProperty('--audio-active', '0');
        root.removeAttribute('data-audio-active');
    }

    _actualizarEstilosCss() {
        let styleTag = document.getElementById('prig-audio-reactive-style');
        if (!styleTag) {
            styleTag = document.createElement('style');
            styleTag.id = 'prig-audio-reactive-style';
            document.head.appendChild(styleTag);
        }

        let css = '';

        if (this.config.efectoBordes) {
            css += `
                :root[data-audio-active="1"] #prig-topbar,
                :root[data-audio-active="1"] #sidebar-left,
                :root[data-audio-active="1"] #sidebar-right,
                :root[data-audio-active="1"] #prig-estado,
                :root[data-audio-active="1"] .panel,
                :root[data-audio-active="1"] .panel-header,
                :root[data-audio-active="1"] .panel-trabajo,
                :root[data-audio-active="1"] .editor-col,
                :root[data-audio-active="1"] .editor-layout-bar,
                :root[data-audio-active="1"] .terminal-container,
                :root[data-audio-active="1"] .tab-bar,
                :root[data-audio-active="1"] #prig-note-headerbar {
                    box-shadow: var(--audio-glow-shadow) !important;
                    border-color: var(--audio-border-color) !important;
                    transition: border-color 0.08s ease, box-shadow 0.08s ease;
                }
            `;
        }

        if (this.config.efectoTopbar) {
            css += `
                :root[data-audio-active="1"] #prig-topbar {
                    border-bottom-color: var(--audio-border-color) !important;
                    box-shadow: var(--audio-glow-topbar) !important;
                }
                :root[data-audio-active="1"] .tab-item.activa,
                :root[data-audio-active="1"] .tab-item.active,
                :root[data-audio-active="1"] .nav-tab.active,
                :root[data-audio-active="1"] .tool-btn.primary,
                :root[data-audio-active="1"] .btn-pestana.activa {
                    box-shadow: var(--audio-glow-shadow) !important;
                    border-color: var(--audio-border-color) !important;
                }
            `;
        }

        if (this.config.efectoSintaxis) {
            css += `
                :root[data-audio-active="1"] .monaco-editor .mtk5,
                :root[data-audio-active="1"] .monaco-editor .mtk6,
                :root[data-audio-active="1"] .monaco-editor .mtk8,
                :root[data-audio-active="1"] .monaco-editor .mtk9,
                :root[data-audio-active="1"] .monaco-editor .mtk20,
                :root[data-audio-active="1"] .monaco-editor .mtk22,
                :root[data-audio-active="1"] .monaco-editor span[class*="mtk"] {
                    text-shadow: var(--audio-text-glow) !important;
                    transition: text-shadow 0.08s ease;
                }
            `;
        }

        styleTag.innerHTML = css;

        if (this._activo) {
            document.documentElement.setAttribute('data-audio-active', '1');
        } else {
            document.documentElement.removeAttribute('data-audio-active');
        }
    }

    _renderizarVisualizadoresNativos() {
        if (!this._spectrumNativo || this._visualizadores.size === 0) return;

        const color = this.obtenerColorLuz();
        const numBarras = 32;

        this._visualizadores.forEach(canvas => {
            if (!canvas || !canvas.isConnected) {
                this._visualizadores.delete(canvas);
                return;
            }

            const ctx = canvas.getContext('2d');
            if (!ctx) return;

            const w = canvas.width;
            const h = canvas.height;

            ctx.clearRect(0, 0, w, h);
            ctx.fillStyle = 'rgba(0, 0, 0, 0.25)';
            ctx.fillRect(0, 0, w, h);

            const gap = 3;
            const anchoBarra = Math.max(2, (w - (numBarras - 1) * gap) / numBarras);

            const grad = ctx.createLinearGradient(0, h, 0, 0);
            grad.addColorStop(0, 'rgba(40, 200, 255, 0.6)');
            grad.addColorStop(0.6, color);
            grad.addColorStop(1.0, '#ffffff');

            for (let i = 0; i < numBarras; i++) {
                const val = this._spectrumNativo[i] || 0;
                const altura = Math.max(3, val * (h - 6));
                const x = i * (anchoBarra + gap);
                const y = h - altura;

                ctx.fillStyle = grad;
                ctx.beginPath();
                ctx.roundRect ? ctx.roundRect(x, y, anchoBarra, altura, [3, 3, 0, 0]) : ctx.fillRect(x, y, anchoBarra, altura);
                ctx.fill();

                if (val > 0.45) {
                    ctx.fillStyle = '#ffffff';
                    ctx.fillRect(x, y, anchoBarra, 2);
                }
            }
        });
    }

    _notificarCambioEstado(tipo, detalle = '') {
        this._actualizarEstilosCss();
        window.dispatchEvent(new CustomEvent('prig_audio_reactivo_estado', {
            detail: {
                tipo,
                activo: this._activo,
                fuente: this._fuenteActual,
                nombre: this._nombreFuenteActual,
                detalle
            }
        }));
    }
}

// Instanciar singleton global
window.AudioReactivoManager = AudioReactivoManager;
window.audioReactivoMgr = new AudioReactivoManager();
