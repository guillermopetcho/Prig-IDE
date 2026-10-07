/**
 * Motor de Movimiento y Animaciones de Fondo de Alto Rendimiento para Prig IDE.
 * 
 * Características clave de optimización:
 * 1. Control de Tasa de Cuadros (FPS Throttling) configurable (30 / 45 / 60 / Ilimitado).
 * 2. Escala de Resolución Inteligente (Downsampling con aceleración GPU de 0.5x, 0.75x a 1.0x).
 * 3. Pausa Automática por Visibilidad (ahorro total de CPU/GPU cuando la pestaña está en segundo plano).
 * 4. Normalización por Delta-Time (animaciones fluidas e independientes de los FPS).
 * 5. Particionamiento espacial en cuadrícula (evita bucles O(N²) en conexiones de partículas).
 * 6. Telemetría en tiempo real (FPS medidos, tiempo de fotograma en ms, conteo de entidades).
 * 7. Arquitectura modular de efectos (registro de nuevos efectos dinámicamente con `registrarEfecto`).
 * 8. Interacción física opcional con el cursor (repulsión magnética, estela, gravedad).
 */

class MotorMovimientoFondo {
    constructor() {
        this.canvas = null;
        this.ctx = null;
        this._animId = null;
        this._efectoActivo = null;
        this._estadoEfecto = {};
        this._efectosRegistrados = new Map();

        // Configuración de rendimiento y calidad
        this.config = {
            efecto: 'particulas',
            fpsLimite: 60,                // 30, 45, 60, 0 (ilimitado)
            escalaRender: 0.75,           // 0.5 (máximo ahorro), 0.75 (balance), 1.0 (fidelidad)
            densidad: 'media',            // 'baja' (0.5x), 'media' (1.0x), 'alta' (1.5x), 'ultra' (2.0x)
            velocidad: 1.0,               // Multiplicador 0.2x a 3.0x
            interaccionMouse: true,       // Respuesta al cursor
            pausarEnSegundoPlano: true,   // Suspender bucle en pestaña inactiva
            opacidad: 0.85                // Opacidad del lienzo
        };

        // Estado del puntero / mouse
        this.mouse = {
            x: -9999,
            y: -9999,
            vx: 0,
            vy: 0,
            isDown: false,
            activo: false,
            ultimoMov: 0
        };

        // Estado del cursor de texto / punto de mecanografía del IDE
        this.cursorTexto = {
            x: -9999,
            y: -9999,
            targetX: -9999,
            targetY: -9999,
            activo: false,
            ultimoDisparo: 0,
            ultimoMov: 0,
            ultimoChar: ''
        };

        // Telemetría de rendimiento
        this.telemetria = {
            fps: 60,
            fpsInstantaneo: 60,
            frameTimeMs: 0,
            elementos: 0,
            estado: 'inactivo',
            _framesAcumulados: 0,
            _ultimoCalculoFps: performance.now()
        };

        // Control de tiempo para el bucle de render
        this._tiempoAnterior = performance.now();
        this._intervaloFps = 1000 / 60;
        this._tiempoUltimoFrame = 0;
        this._estaVisible = true;
        this._usuarioScript = null;

        // Cargar configuración guardada
        this._cargarConfig();

        // Sincronizar con el backend
        this.sincronizarBackend();

        // Registrar todos los efectos predeterminados
        this._registrarEfectosNativos();

        // Configurar listeners globales de ventana y mouse
        this._iniciarListeners();
    }

    _cargarConfig() {
        try {
            const raw = localStorage.getItem('prig_motor_movimiento');
            if (raw) {
                const guardado = JSON.parse(raw);
                this.config = { ...this.config, ...guardado };
            }
        } catch (e) {
            // Usar valores por defecto
        }
        this._actualizarIntervaloFps();
    }

    async sincronizarBackend() {
        try {
            const res = await fetch('/api/config/motor_movimiento');
            if (res.ok) {
                const data = await res.json();
                if (data && typeof data === 'object' && Object.keys(data).length > 0 && data.efecto) {
                    this.config = { ...this.config, ...data };
                    try {
                        localStorage.setItem('prig_motor_movimiento', JSON.stringify(this.config));
                    } catch (e) {}
                    this._actualizarIntervaloFps();
                } else if (!localStorage.getItem('prig_motor_movimiento')) {
                    this._guardarBackendInmediato();
                }
            }
        } catch (e) {
            // Silencioso
        }
    }

    _guardarBackendInmediato() {
        try {
            fetch('/api/config/motor_movimiento', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(this.config)
            }).catch(() => {});
        } catch (e) {}
    }

    guardarConfig() {
        try {
            localStorage.setItem('prig_motor_movimiento', JSON.stringify(this.config));
        } catch (e) {
            console.warn("No se pudo guardar la configuración del motor de movimiento:", e);
        }

        if (this._guardarTimer) clearTimeout(this._guardarTimer);
        this._guardarTimer = setTimeout(() => {
            this._guardarBackendInmediato();
        }, 200);
    }

    _actualizarIntervaloFps() {
        const fps = this.config.fpsLimite || 60;
        this._intervaloFps = fps > 0 ? (1000 / fps) : 0;
    }

    // ==========================================
    // INICIALIZACIÓN DEL CANVAS Y EVENTOS
    // ==========================================

    _asegurarCanvas() {
        if (!this.canvas) {
            let el = document.getElementById('prig-canvas-fondo');
            if (!el) {
                el = document.createElement('canvas');
                el.id = 'prig-canvas-fondo';
                el.style.cssText = 'position: fixed; inset: 0; width: 100vw; height: 100vh; pointer-events: none; z-index: 0; display: block; image-rendering: auto;';
                document.body.prepend(el);
            }
            this.canvas = el;
            this.ctx = el.getContext('2d', { alpha: true, desynchronized: true });
        }
        this.redimensionar();
    }

    redimensionar() {
        if (!this.canvas) return;
        const escala = Math.max(0.33, Math.min(1.0, this.config.escalaRender || 0.75));
        const anchoReal = Math.floor(window.innerWidth * escala);
        const altoReal = Math.floor(window.innerHeight * escala);

        if (this.canvas.width !== anchoReal || this.canvas.height !== altoReal) {
            this.canvas.width = anchoReal;
            this.canvas.height = altoReal;
            
            // Si el efecto actual tiene hook de redimensionado o init, avisarle
            if (this._efectoActivo && this._efectosRegistrados.has(this._efectoActivo)) {
                const def = this._efectosRegistrados.get(this._efectoActivo);
                if (typeof def.onResize === 'function') {
                    def.onResize(anchoReal, altoReal, this._estadoEfecto);
                }
            }
        }
    }

    _iniciarListeners() {
        // Control de redimensionado suave con debounce
        let resizeTimer = null;
        window.addEventListener('resize', () => {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(() => this.redimensionar(), 120);
        });

        // Pausa inteligente al cambiar de pestaña o minimizar
        document.addEventListener('visibilitychange', () => {
            this._estaVisible = !document.hidden;
            if (this.config.pausarEnSegundoPlano) {
                if (document.hidden) {
                    this.telemetria.estado = 'dormido';
                } else {
                    this._tiempoAnterior = performance.now();
                    this.telemetria.estado = 'activo';
                }
            }
        });

        // Monitoreo de mouse throttled
        window.addEventListener('pointermove', (e) => {
            if (!this.config.interaccionMouse) return;
            const escala = this.config.escalaRender || 0.75;
            const nuevoX = e.clientX * escala;
            const nuevoY = e.clientY * escala;
            this.mouse.vx = nuevoX - this.mouse.x;
            this.mouse.vy = nuevoY - this.mouse.y;
            this.mouse.x = nuevoX;
            this.mouse.y = nuevoY;
            this.mouse.activo = true;
            this.mouse.ultimoMov = performance.now();
        }, { passive: true });

        window.addEventListener('pointerdown', () => {
            this.mouse.isDown = true;
        }, { passive: true });

        window.addEventListener('pointerup', () => {
            this.mouse.isDown = false;
        }, { passive: true });

        window.addEventListener('pointerleave', () => {
            this.mouse.activo = false;
            this.mouse.x = -9999;
            this.mouse.y = -9999;
        }, { passive: true });

        // Listener global de teclado para detectar mecanografía en cualquier campo de texto
        window.addEventListener('keydown', (e) => {
            if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) {
                const rect = e.target.getBoundingClientRect();
                const screenX = rect.left + rect.width / 2;
                const screenY = rect.top + rect.height / 2;
                this.notificarPosicionCursor(screenX, screenY);
                if (e.key && e.key.length === 1) {
                    this.dispararHaciaCursor(screenX, screenY, e.key);
                }
            }
        }, { passive: true });
    }

    // ==========================================
    // SEGUIMIENTO DE CURSOR Y DISPARO AL ESCRIBIR
    // ==========================================

    notificarPosicionCursor(x, y) {
        const escala = this.config.escalaRender || 0.75;
        this.cursorTexto.x = x * escala;
        this.cursorTexto.y = y * escala;
        this.cursorTexto.targetX = x * escala;
        this.cursorTexto.targetY = y * escala;
        this.cursorTexto.activo = true;
        this.cursorTexto.ultimoMov = performance.now();
    }

    dispararHaciaCursor(x, y, char = null) {
        const escala = this.config.escalaRender || 0.75;
        const targetX = x * escala;
        const targetY = y * escala;
        this.cursorTexto.x = targetX;
        this.cursorTexto.y = targetY;
        this.cursorTexto.targetX = targetX;
        this.cursorTexto.targetY = targetY;
        this.cursorTexto.activo = true;
        this.cursorTexto.ultimoDisparo = performance.now();
        this.cursorTexto.ultimoChar = char || 'λ';

        // Enviar evento de disparo al efecto activo si cuenta con hook onDisparo
        if (this._efectoActivo && this._efectosRegistrados.has(this._efectoActivo)) {
            const def = this._efectosRegistrados.get(this._efectoActivo);
            if (typeof def.onDisparo === 'function') {
                def.onDisparo(targetX, targetY, char, this._estadoEfecto);
            }
        }
    }

    // ==========================================
    // SISTEMA MODULAR DE EFECTOS
    // ==========================================

    registrarEfecto(id, definicion) {
        if (!id || typeof definicion !== 'object') return;
        this._efectosRegistrados.set(id, {
            id,
            nombre: definicion.nombre || id,
            icono: definicion.icono || 'fa-sparkles',
            desc: definicion.desc || '',
            init: definicion.init || (() => ({})),
            update: definicion.update || (() => {}),
            render: definicion.render || (() => {}),
            destroy: definicion.destroy || (() => {}),
            onResize: definicion.onResize || null,
            onDisparo: definicion.onDisparo || null
        });
    }

    obtenerListaEfectos() {
        const lista = [];
        this._efectosRegistrados.forEach((def, id) => {
            lista.push({
                id,
                nombre: def.nombre,
                icono: def.icono,
                desc: def.desc
            });
        });
        return lista;
    }

    _getMultiplicadorDensidad() {
        const d = this.config.densidad;
        if (d === 'baja') return 0.5;
        if (d === 'alta') return 1.5;
        if (d === 'ultra') return 2.2;
        return 1.0; // 'media'
    }

    activarEfecto(id, configExtra = {}) {
        if (!this._efectosRegistrados.has(id) && id !== 'codigo_js') {
            console.warn(`Efecto de movimiento "${id}" no registrado. Usando particulas por defecto.`);
            id = 'particulas';
        }

        // Destruir efecto anterior si existía
        if (this._efectoActivo && this._efectosRegistrados.has(this._efectoActivo)) {
            const defAnt = this._efectosRegistrados.get(this._efectoActivo);
            if (typeof defAnt.destroy === 'function') {
                defAnt.destroy(this._estadoEfecto);
            }
        }

        this._efectoActivo = id;
        this.config.efecto = id;
        this.guardarConfig();

        this._asegurarCanvas();
        this.canvas.style.display = 'block';

        const w = this.canvas.width;
        const h = this.canvas.height;
        const densidad = this._getMultiplicadorDensidad();

        // Notificar al Director ASCII sobre el cambio de tema para que cargue el contexto correspondiente
        if (window.DIRECTOR_ASCII) {
            window.DIRECTOR_ASCII.inicializarEscenario(id);
        }

        if (id === 'codigo_js') {
            this._iniciarCodigoUsuario(configExtra.codigoJs);
        } else {
            const def = this._efectosRegistrados.get(id);
            this._estadoEfecto = def.init(this.canvas, w, h, densidad, this.config) || {};
        }

        this._iniciarBucle();
    }

    detener() {
        if (this._animId) {
            cancelAnimationFrame(this._animId);
            this._animId = null;
        }
        if (this.canvas) {
            this.canvas.style.display = 'none';
        }
        this.telemetria.estado = 'detenido';
    }

    setOpcion(clave, valor) {
        this.config[clave] = valor;
        this.guardarConfig();

        if (clave === 'fpsLimite') {
            this._actualizarIntervaloFps();
        } else if (clave === 'escalaRender') {
            this.redimensionar();
        } else if (clave === 'densidad' || clave === 'velocidad') {
            // Reiniciar estado del efecto para aplicar nueva densidad/velocidad
            if (this._efectoActivo) {
                this.activarEfecto(this._efectoActivo);
            }
        }
    }

    // ==========================================
    // BUCLE PRINCIPAL DE ANIMACIÓN (LOOP)
    // ==========================================

    _iniciarBucle() {
        if (this._animId) {
            cancelAnimationFrame(this._animId);
        }
        this._tiempoAnterior = performance.now();
        this.telemetria._ultimoCalculoFps = performance.now();
        this.telemetria._framesAcumulados = 0;
        this.telemetria.estado = 'activo';

        const bucle = (ahora) => {
            this._animId = requestAnimationFrame(bucle);

            // Ahorro total si la ventana está oculta y configurada para pausar
            if (!this._estaVisible && this.config.pausarEnSegundoPlano) {
                return;
            }

            // Limitador de FPS por intervalo de tiempo
            if (this._intervaloFps > 0) {
                const transcurrido = ahora - this._tiempoUltimoFrame;
                if (transcurrido < this._intervaloFps - 1.5) {
                    return; // Saltar fotograma para no sobrecargar la GPU
                }
                this._tiempoUltimoFrame = ahora - (transcurrido % this._intervaloFps);
            }

            // Cálculo de Delta Time normalizado en segundos (limitado a 0.1s para evitar saltos enormes)
            const dtRaw = (ahora - this._tiempoAnterior) / 1000;
            this._tiempoAnterior = ahora;
            const dt = Math.min(0.1, dtRaw) * (this.config.velocidad || 1.0);

            // Iniciar medición de telemetría del frame
            const tInicioFrame = performance.now();

            // Renderizar frame
            this._renderFrame(ahora, dt);

            // Medir tiempo de ejecución del frame
            const tFinFrame = performance.now();
            this.telemetria.frameTimeMs = +(tFinFrame - tInicioFrame).toFixed(1);

            // Calcular FPS reales promedio cada 500 ms
            this.telemetria._framesAcumulados++;
            const tiempoDesdeUltimoCalculo = ahora - this.telemetria._ultimoCalculoFps;
            if (tiempoDesdeUltimoCalculo >= 500) {
                this.telemetria.fps = Math.round((this.telemetria._framesAcumulados * 1000) / tiempoDesdeUltimoCalculo);
                this.telemetria._framesAcumulados = 0;
                this.telemetria._ultimoCalculoFps = ahora;
            }
        };

        this._animId = requestAnimationFrame(bucle);
    }

    _renderFrame(tiempoTotal, dt) {
        if (!this.ctx || !this.canvas) return;

        const w = this.canvas.width;
        const h = this.canvas.height;

        // Desactivar mouse si lleva más de 3 segundos inactivo
        if (this.mouse.activo && (performance.now() - this.mouse.ultimoMov > 3000)) {
            this.mouse.activo = false;
        }

        if (this._efectoActivo === 'codigo_js') {
            if (typeof this._usuarioScript === 'function') {
                try {
                    this._usuarioScript(this.canvas, this.ctx, w, h, tiempoTotal, dt, this.mouse);
                } catch (e) {
                    // Evitar que un error en el script de usuario rompa el loop
                }
            }
            return;
        }

        const def = this._efectosRegistrados.get(this._efectoActivo);
        if (!def) return;

        // Factores de modulación reactiva por audio (si está activo)
        const audio = (window.audioReactivoMgr && typeof window.audioReactivoMgr.getFactoresMovimiento === 'function')
            ? window.audioReactivoMgr.getFactoresMovimiento()
            : { reactivo: false, boostVelocidad: 1.0, boostTamano: 1.0, boostBrillo: 1.0, energia: 0, energiaBass: 0, energiaTreble: 0 };

        const dtEfectivo = dt * (audio.reactivo ? audio.boostVelocidad : 1.0);

        // 1. Update de la física
        if (typeof def.update === 'function') {
            def.update(dtEfectivo, w, h, this.mouse, this._estadoEfecto, audio, this.cursorTexto);
        }

        // 2. Renderizado en el Canvas
        if (typeof def.render === 'function') {
            def.render(this.ctx, w, h, dtEfectivo, this.mouse, this._estadoEfecto, tiempoTotal, audio, this.cursorTexto);
        }

        // 3. Renderizado universal del Director ASCII y Agentes Autónomos LLM en todos los efectos
        if (window.DIRECTOR_ASCII && this._efectoActivo && !this._efectoActivo.startsWith('tema_')) {
            window.DIRECTOR_ASCII.actualizar(dtEfectivo, this.cursorTexto, w, h);
            window.DIRECTOR_ASCII.dibujar(this.ctx, w, h);
        }
    }

    // ==========================================
    // EJECUCIÓN DE CÓDIGO DE USUARIO EN VIVO
    // ==========================================

    _iniciarCodigoUsuario(codigo) {
        try {
            const fnStr = codigo || `
                // Script de usuario
                function render(ctx, width, height, time) {
                    ctx.clearRect(0, 0, width, height);
                }
            `;
            this._usuarioScript = new Function('canvas', 'ctx', 'width', 'height', 'time', 'dt', 'mouse', `
                try {
                    ${fnStr}
                    if (typeof render === 'function') {
                        render(ctx, width, height, time, dt, mouse);
                    }
                } catch (err) {
                    // Capturado
                }
            `);
        } catch (e) {
            console.warn("Error compilando script de fondo de usuario:", e);
            this._usuarioScript = null;
        }
    }

    ejecutarCodigoUsuario(codigo) {
        this._efectoActivo = 'codigo_js';
        this._iniciarCodigoUsuario(codigo);
        this._asegurarCanvas();
        this.canvas.style.display = 'block';
        this._iniciarBucle();
    }

    // ==========================================
    // CATÁLOGO COMPLETO DE EFECTOS NATIVOS
    // ==========================================

    _registrarEfectosNativos() {

        // -------------------------------------------------------------
        // 1. CONSTELACIÓN NEURONAL (Partículas con Física y Conexión Espacial)
        // -------------------------------------------------------------
        this.registrarEfecto('particulas', {
            nombre: 'Constelación Neuronal',
            icono: 'fa-circle-nodes',
            desc: 'Red neuronal interactiva de nodos conectados con física de repulsión al cursor.',
            init: (canvas, w, h, densidad) => {
                const cantidad = Math.floor(65 * densidad);
                const colores = ['#89b4fa', '#cba6f7', '#a6e3a1', '#f9e2af', '#89dceb'];
                const particulas = [];

                for (let i = 0; i < cantidad; i++) {
                    particulas.push({
                        x: Math.random() * w,
                        y: Math.random() * h,
                        vx: (Math.random() - 0.5) * 45,
                        vy: (Math.random() - 0.5) * 45,
                        r: Math.random() * 2.2 + 1.2,
                        col: colores[i % colores.length],
                        brillo: Math.random() * 0.5 + 0.5
                    });
                }
                return { particulas, distMax: 120, distMouse: 150 };
            },
            update: (dt, w, h, mouse, state) => {
                const p = state.particulas;
                const dMouseSq = state.distMouse * state.distMouse;

                for (let i = 0; i < p.length; i++) {
                    const pt = p[i];
                    pt.x += pt.vx * dt;
                    pt.y += pt.vy * dt;

                    // Rebote en bordes con amortiguación
                    if (pt.x < 0) { pt.x = 0; pt.vx *= -1; }
                    else if (pt.x > w) { pt.x = w; pt.vx *= -1; }
                    if (pt.y < 0) { pt.y = 0; pt.vy *= -1; }
                    else if (pt.y > h) { pt.y = h; pt.vy *= -1; }

                    // Interacción física con el mouse (Repulsión suave)
                    if (mouse.activo) {
                        const dx = pt.x - mouse.x;
                        const dy = pt.y - mouse.y;
                        const distSq = dx * dx + dy * dy;
                        if (distSq < dMouseSq && distSq > 0.1) {
                            const dist = Math.sqrt(distSq);
                            const fuerza = (1 - dist / state.distMouse) * 160;
                            pt.x += (dx / dist) * fuerza * dt;
                            pt.y += (dy / dist) * fuerza * dt;
                        }
                    }
                }
            },
            render: (ctx, w, h, dt, mouse, state, time, audio) => {
                ctx.clearRect(0, 0, w, h);
                const p = state.particulas;
                const boostTam = (audio && audio.reactivo) ? audio.boostTamano : 1.0;
                const boostBri = (audio && audio.reactivo) ? audio.boostBrillo : 1.0;
                const distMax = state.distMax * boostTam;
                const distMaxSq = distMax * distMax;

                // Conexiones de líneas (optimizado)
                for (let i = 0; i < p.length; i++) {
                    const p1 = p[i];
                    for (let j = i + 1; j < p.length; j++) {
                        const p2 = p[j];
                        const dx = p1.x - p2.x;
                        const dy = p1.y - p2.y;
                        const distSq = dx * dx + dy * dy;

                        if (distSq < distMaxSq) {
                            const alfa = (1 - Math.sqrt(distSq) / distMax) * (0.28 * boostBri);
                            ctx.strokeStyle = (audio && audio.reactivo && audio.energia > 0.45) ? audio.colorLuz : `rgba(137, 180, 250, ${Math.min(1.0, alfa)})`;
                            ctx.lineWidth = (audio && audio.reactivo && audio.energia > 0.5) ? 1.8 : 1;
                            ctx.beginPath();
                            ctx.moveTo(p1.x, p1.y);
                            ctx.lineTo(p2.x, p2.y);
                            ctx.stroke();
                        }
                    }
                }

                // Dibujar nodos
                for (let i = 0; i < p.length; i++) {
                    const pt = p[i];
                    ctx.fillStyle = pt.col;
                    ctx.shadowColor = (audio && audio.reactivo && audio.energia > 0.35) ? audio.colorLuz : pt.col;
                    ctx.shadowBlur = 6 * boostBri;
                    ctx.beginPath();
                    ctx.arc(pt.x, pt.y, pt.r * boostTam, 0, Math.PI * 2);
                    ctx.fill();
                }
            }
        });

        // -------------------------------------------------------------
        // 2. LLUVIA DIGITAL MATRIX CYBERPUNK
        // -------------------------------------------------------------
        this.registrarEfecto('matrix', {
            nombre: 'Lluvia Digital Matrix',
            icono: 'fa-terminal',
            desc: 'Caracteres digitales verdes y cian cayendo en cascada con estela cyberpunk.',
            init: (canvas, w, h, densidad) => {
                const chars = '0123456789ABCDEFｦｱｳｴｵｶｷｹｺｻｼｽｾｿﾀﾂﾃﾅﾆﾇﾈﾊﾋﾎﾏﾐﾑﾒﾓﾔﾕﾗﾘﾜ';
                const colWidth = 15;
                const cols = Math.floor(w / colWidth) + 1;
                const gotas = [];
                const velocidades = [];

                for (let i = 0; i < cols; i++) {
                    gotas.push(Math.random() * -h);
                    velocidades.push(Math.random() * 200 + 180);
                }
                return { chars, colWidth, gotas, velocidades };
            },
            update: (dt, w, h, mouse, state, audio) => {
                const gotas = state.gotas;
                const vels = state.velocidades;
                for (let i = 0; i < gotas.length; i++) {
                    gotas[i] += vels[i] * dt;
                    if (gotas[i] > h && Math.random() > 0.96) {
                        gotas[i] = Math.random() * -60;
                    }
                }
            },
            render: (ctx, w, h, dt, mouse, state, time, audio) => {
                // Fondo con desvanecimiento para efecto estela
                ctx.fillStyle = 'rgba(10, 10, 20, 0.09)';
                ctx.fillRect(0, 0, w, h);

                ctx.font = '13px monospace';
                const gotas = state.gotas;
                const chars = state.chars;
                const colWidth = state.colWidth;
                const boostBri = (audio && audio.reactivo) ? audio.boostBrillo : 1.0;

                for (let i = 0; i < gotas.length; i++) {
                    const char = chars[Math.floor(Math.random() * chars.length)];
                    const x = i * colWidth;
                    const y = gotas[i];

                    const esLider = Math.random() > 0.88;
                    ctx.fillStyle = esLider ? '#a6e3a1' : ((audio && audio.reactivo && audio.energia > 0.4) ? audio.colorLuz : '#00f0ff');
                    ctx.shadowColor = esLider ? '#a6e3a1' : ((audio && audio.reactivo && audio.energia > 0.3) ? audio.colorLuz : '#00f0ff');
                    ctx.shadowBlur = (esLider ? 8 : 4) * boostBri;
                    ctx.fillText(char, x, y);
                }
            }
        });

        // -------------------------------------------------------------
        // 3. CAMPO DE ESTRELLAS 3D (Hyperspace Warp)
        // -------------------------------------------------------------
        this.registrarEfecto('estrellas', {
            nombre: 'Campo de Estrellas 3D',
            icono: 'fa-star',
            desc: 'Viaje espacial a velocidad hiperespacial con estrellas viajando en profundidad 3D.',
            init: (canvas, w, h, densidad) => {
                const cantidad = Math.floor(180 * densidad);
                const estrellas = [];
                for (let i = 0; i < cantidad; i++) {
                    estrellas.push({
                        x: (Math.random() - 0.5) * w * 2,
                        y: (Math.random() - 0.5) * h * 2,
                        z: Math.random() * w
                    });
                }
                return { estrellas, velocidadZ: 300 };
            },
            update: (dt, w, h, mouse, state, audio) => {
                const est = state.estrellas;
                const vZ = (mouse.activo && mouse.isDown ? state.velocidadZ * 2.5 : state.velocidadZ) * dt;

                for (let i = 0; i < est.length; i++) {
                    const s = est[i];
                    s.z -= vZ;
                    if (s.z <= 1) {
                        s.z = w;
                        s.x = (Math.random() - 0.5) * w * 2;
                        s.y = (Math.random() - 0.5) * h * 2;
                    }
                }
            },
            render: (ctx, w, h, dt, mouse, state, time, audio) => {
                ctx.fillStyle = 'rgba(10, 10, 20, 0.25)';
                ctx.fillRect(0, 0, w, h);

                const est = state.estrellas;
                const cx = w / 2;
                const cy = h / 2;
                const boostTam = (audio && audio.reactivo) ? audio.boostTamano : 1.0;
                const boostBri = (audio && audio.reactivo) ? audio.boostBrillo : 1.0;

                for (let i = 0; i < est.length; i++) {
                    const s = est[i];
                    const k = 220 / s.z;
                    const px = s.x * k + cx;
                    const py = s.y * k + cy;

                    if (px >= 0 && px <= w && py >= 0 && py <= h) {
                        const size = Math.max(0.6, (1 - s.z / w) * 3.5) * boostTam;
                        const brillo = Math.min(1.0, (1 - s.z / w) * boostBri);
                        ctx.fillStyle = (audio && audio.reactivo && audio.energia > 0.45) ? audio.colorLuz : `rgba(205, 214, 244, ${brillo})`;
                        ctx.shadowColor = (audio && audio.reactivo && audio.energia > 0.3) ? audio.colorLuz : '#89b4fa';
                        ctx.shadowBlur = (size > 2 ? 6 : 2) * boostBri;
                        ctx.beginPath();
                        ctx.arc(px, py, size, 0, Math.PI * 2);
                        ctx.fill();
                    }
                }
            }
        });

        // -------------------------------------------------------------
        // 4. AURORA BOREAL FLUIDA
        // -------------------------------------------------------------
        this.registrarEfecto('aurora', {
            nombre: 'Aurora Boreal Fluida',
            icono: 'fa-water',
            desc: 'Olas continuas de luz de colores etéreos fluyendo y refractándose suavemente.',
            init: (canvas, w, h) => {
                return {
                    capas: [
                        { color: 'rgba(137, 180, 250, 0.18)', freq: 0.003, speed: 0.5, yOff: 0.35, amp: 70 },
                        { color: 'rgba(203, 166, 247, 0.16)', freq: 0.004, speed: 0.7, yOff: 0.50, amp: 85 },
                        { color: 'rgba(166, 227, 161, 0.14)', freq: 0.002, speed: 0.4, yOff: 0.65, amp: 60 }
                    ]
                };
            },
            render: (ctx, w, h, dt, mouse, state, time, audio) => {
                ctx.clearRect(0, 0, w, h);
                const t = time * 0.001;
                const boostTam = (audio && audio.reactivo) ? audio.boostTamano : 1.0;

                state.capas.forEach(capa => {
                    ctx.fillStyle = capa.color;
                    ctx.beginPath();
                    ctx.moveTo(0, h);

                    const paso = 16;
                    const ampMod = capa.amp * boostTam;
                    for (let x = 0; x <= w + paso; x += paso) {
                        const yBase = h * capa.yOff;
                        const y = yBase + Math.sin(x * capa.freq + t * capa.speed) * ampMod + Math.cos(x * capa.freq * 0.5 - t * 0.3) * (ampMod * 0.5);
                        ctx.lineTo(x, y);
                    }

                    ctx.lineTo(w, h);
                    ctx.closePath();
                    ctx.fill();
                });
            }
        });

        // -------------------------------------------------------------
        // 5. LUCES NEÓN BOKEH FLOTANTES
        // -------------------------------------------------------------
        this.registrarEfecto('bokeh', {
            nombre: 'Luces Neón Bokeh',
            icono: 'fa-lightbulb',
            desc: 'Orbes luminosos desenfocados pulsando suavemente y elevándose por la pantalla.',
            init: (canvas, w, h, densidad) => {
                const cantidad = Math.floor(30 * densidad);
                const colores = [
                    'rgba(137, 180, 250, 0.16)',
                    'rgba(203, 166, 247, 0.14)',
                    'rgba(166, 227, 161, 0.13)',
                    'rgba(249, 226, 175, 0.12)'
                ];
                const orbes = [];
                for (let i = 0; i < cantidad; i++) {
                    orbes.push({
                        x: Math.random() * w,
                        y: Math.random() * h,
                        r: Math.random() * 55 + 25,
                        vy: -(Math.random() * 25 + 10),
                        vx: (Math.random() - 0.5) * 15,
                        col: colores[i % colores.length],
                        fase: Math.random() * Math.PI * 2
                    });
                }
                return { orbes };
            },
            update: (dt, w, h, mouse, state, audio) => {
                const orbes = state.orbes;
                for (let i = 0; i < orbes.length; i++) {
                    const o = orbes[i];
                    o.y += o.vy * dt;
                    o.x += o.vx * dt;
                    o.fase += dt * 1.5;

                    if (o.y < -o.r * 2) {
                        o.y = h + o.r;
                        o.x = Math.random() * w;
                    }
                    if (o.x < -o.r) o.x = w + o.r;
                    else if (o.x > w + o.r) o.x = -o.r;
                }
            },
            render: (ctx, w, h, dt, mouse, state, time, audio) => {
                ctx.clearRect(0, 0, w, h);
                const orbes = state.orbes;
                const boostTam = (audio && audio.reactivo) ? audio.boostTamano : 1.0;
                for (let i = 0; i < orbes.length; i++) {
                    const o = orbes[i];
                    const pulso = Math.sin(o.fase) * 0.2 + 0.8;
                    const radioActual = o.r * pulso * boostTam;

                    const grad = ctx.createRadialGradient(o.x, o.y, 0, o.x, o.y, radioActual);
                    grad.addColorStop(0, o.col);
                    grad.addColorStop(1, 'rgba(0,0,0,0)');

                    ctx.fillStyle = grad;
                    ctx.beginPath();
                    ctx.arc(o.x, o.y, radioActual, 0, Math.PI * 2);
                    ctx.fill();
                }
            }
        });

        // -------------------------------------------------------------
        // 6. OLAS LÍQUIDAS SINUSOIDALES
        // -------------------------------------------------------------
        this.registrarEfecto('ondas_liquidas', {
            nombre: 'Olas Líquidas Neón',
            icono: 'fa-wave-square',
            desc: 'Líneas senoidales líquidas de interferencia con resplandor neón.',
            init: () => ({
                lineas: [
                    { col: '#89b4fa', speed: 1.2, freq: 0.005, amp: 50 },
                    { col: '#cba6f7', speed: 1.6, freq: 0.004, amp: 65 },
                    { col: '#a6e3a1', speed: 0.9, freq: 0.006, amp: 40 },
                    { col: '#f9e2af', speed: 1.4, freq: 0.003, amp: 55 }
                ]
            }),
            render: (ctx, w, h, dt, mouse, state, time, audio) => {
                ctx.fillStyle = 'rgba(10, 10, 20, 0.2)';
                ctx.fillRect(0, 0, w, h);

                const t = time * 0.001;
                const centerY = h / 2;
                const boostTam = (audio && audio.reactivo) ? audio.boostTamano : 1.0;
                const boostBri = (audio && audio.reactivo) ? audio.boostBrillo : 1.0;

                state.lineas.forEach(l => {
                    ctx.strokeStyle = (audio && audio.reactivo && audio.energia > 0.4) ? audio.colorLuz : l.col;
                    ctx.lineWidth = 2.2 * (audio && audio.reactivo ? Math.min(2.0, boostTam) : 1.0);
                    ctx.shadowColor = (audio && audio.reactivo && audio.energia > 0.3) ? audio.colorLuz : l.col;
                    ctx.shadowBlur = 10 * boostBri;
                    ctx.beginPath();

                    const ampMod = l.amp * boostTam;
                    for (let x = 0; x <= w; x += 10) {
                        const y = centerY + Math.sin(x * l.freq + t * l.speed) * ampMod + Math.cos(x * 0.002 - t * 0.5) * (20 * boostTam);
                        if (x === 0) ctx.moveTo(x, y);
                        else ctx.lineTo(x, y);
                    }
                    ctx.stroke();
                });
            }
        });

        // -------------------------------------------------------------
        // 7. MALLA 3D RETRO SYNTHWAVE
        // -------------------------------------------------------------
        this.registrarEfecto('malla_cyberpunk', {
            nombre: 'Cuadrícula 3D Synthwave',
            icono: 'fa-border-all',
            desc: 'Malla tridimensional en perspectiva con horizonte ondulante estilo Synthwave.',
            init: () => ({ offset: 0 }),
            update: (dt, w, h, mouse, state) => {
                state.offset = (state.offset + dt * 45) % 40;
            },
            render: (ctx, w, h, dt, mouse, state) => {
                ctx.clearRect(0, 0, w, h);
                const horizonte = h * 0.45;

                ctx.strokeStyle = 'rgba(203, 166, 247, 0.35)';
                ctx.lineWidth = 1.2;
                ctx.shadowColor = '#cba6f7';
                ctx.shadowBlur = 4;

                // Líneas horizontales en perspectiva
                for (let y = horizonte; y < h; y += 18) {
                    const factor = (y - horizonte) / (h - horizonte);
                    const yPos = horizonte + Math.pow(factor, 1.8) * (h - horizonte) + (state.offset * factor * 0.3);
                    if (yPos > h) continue;

                    ctx.beginPath();
                    ctx.moveTo(0, yPos);
                    ctx.lineTo(w, yPos);
                    ctx.stroke();
                }

                // Líneas verticales convergentes
                const centroX = w / 2;
                const numLineas = 16;
                for (let i = -numLineas; i <= numLineas; i++) {
                    const xBottom = centroX + (i * (w / numLineas) * 1.5);
                    ctx.beginPath();
                    ctx.moveTo(centroX, horizonte);
                    ctx.lineTo(xBottom, h);
                    ctx.stroke();
                }
            }
        });

        // -------------------------------------------------------------
        // 8. ENJAMBRE CUÁNTICO DE POLÍGONOS
        // -------------------------------------------------------------
        this.registrarEfecto('poligonos_cuanticos', {
            nombre: 'Polígonos Cuánticos',
            icono: 'fa-shapes',
            desc: 'Formas geométricas translúcidas que rotan suavemente e interactúan en el espacio.',
            init: (canvas, w, h, densidad) => {
                const cantidad = Math.floor(22 * densidad);
                const formas = [];
                for (let i = 0; i < cantidad; i++) {
                    formas.push({
                        x: Math.random() * w,
                        y: Math.random() * h,
                        vx: (Math.random() - 0.5) * 30,
                        vy: (Math.random() - 0.5) * 30,
                        lados: Math.floor(Math.random() * 4) + 3, // 3: triángulo, 4: cuadrado, 5: pentágono, 6: hexágono
                        radio: Math.random() * 35 + 15,
                        angulo: Math.random() * Math.PI * 2,
                        vAngulo: (Math.random() - 0.5) * 1.5,
                        col: ['rgba(137, 180, 250, 0.15)', 'rgba(203, 166, 247, 0.15)', 'rgba(166, 227, 161, 0.15)'][i % 3]
                    });
                }
                return { formas };
            },
            update: (dt, w, h, mouse, state) => {
                const formas = state.formas;
                for (let i = 0; i < formas.length; i++) {
                    const f = formas[i];
                    f.x += f.vx * dt;
                    f.y += f.vy * dt;
                    f.angulo += f.vAngulo * dt;

                    if (f.x < -f.radio) f.x = w + f.radio;
                    else if (f.x > w + f.radio) f.x = -f.radio;
                    if (f.y < -f.radio) f.y = h + f.radio;
                    else if (f.y > h + f.radio) f.y = -f.radio;
                }
            },
            render: (ctx, w, h, dt, mouse, state) => {
                ctx.clearRect(0, 0, w, h);
                const formas = state.formas;

                for (let i = 0; i < formas.length; i++) {
                    const f = formas[i];
                    ctx.save();
                    ctx.translate(f.x, f.y);
                    ctx.rotate(f.angulo);

                    ctx.fillStyle = f.col;
                    ctx.strokeStyle = f.col.replace('0.15', '0.45');
                    ctx.lineWidth = 1.5;
                    ctx.beginPath();

                    for (let j = 0; j < f.lados; j++) {
                        const a = (j / f.lados) * Math.PI * 2;
                        const px = Math.cos(a) * f.radio;
                        const py = Math.sin(a) * f.radio;
                        if (j === 0) ctx.moveTo(px, py);
                        else ctx.lineTo(px, py);
                    }
                    ctx.closePath();
                    ctx.fill();
                    ctx.stroke();
                    ctx.restore();
                }
            }
        });

        // -------------------------------------------------------------
        // 9. LLUVIA NEÓN EN CRISTAL
        // -------------------------------------------------------------
        this.registrarEfecto('lluvia_neon', {
            nombre: 'Lluvia Neón en Cristal',
            icono: 'fa-cloud-rain',
            desc: 'Gotas de lluvia luminosas cayendo a diferentes profundidades y velocidades.',
            init: (canvas, w, h, densidad) => {
                const cantidad = Math.floor(90 * densidad);
                const gotas = [];
                for (let i = 0; i < cantidad; i++) {
                    gotas.push({
                        x: Math.random() * w,
                        y: Math.random() * h,
                        long: Math.random() * 20 + 10,
                        vel: Math.random() * 400 + 350,
                        grosor: Math.random() * 1.5 + 0.8,
                        alfa: Math.random() * 0.4 + 0.2
                    });
                }
                return { gotas };
            },
            update: (dt, w, h, mouse, state) => {
                const gotas = state.gotas;
                for (let i = 0; i < gotas.length; i++) {
                    const g = gotas[i];
                    g.y += g.vel * dt;
                    g.x += (mouse.activo ? mouse.vx * 0.1 : 0) * dt;
                    if (g.y > h) {
                        g.y = -g.long;
                        g.x = Math.random() * w;
                    }
                }
            },
            render: (ctx, w, h, dt, mouse, state) => {
                ctx.clearRect(0, 0, w, h);
                const gotas = state.gotas;
                for (let i = 0; i < gotas.length; i++) {
                    const g = gotas[i];
                    ctx.strokeStyle = `rgba(137, 180, 250, ${g.alfa})`;
                    ctx.lineWidth = g.grosor;
                    ctx.beginPath();
                    ctx.moveTo(g.x, g.y);
                    ctx.lineTo(g.x - 2, g.y + g.long);
                    ctx.stroke();
                }
            }
        });

        // -------------------------------------------------------------
        // 10. LUCIÉRNAGAS EN EL BOSQUE (Fuego Fatuo)
        // -------------------------------------------------------------
        this.registrarEfecto('fuego_fatuo', {
            nombre: 'Luciérnagas del Bosque',
            icono: 'fa-wand-magic',
            desc: 'Partículas orgánicas con parpadeo suave y movimiento Browniano natural.',
            init: (canvas, w, h, densidad) => {
                const cantidad = Math.floor(45 * densidad);
                const luciernagas = [];
                for (let i = 0; i < cantidad; i++) {
                    luciernagas.push({
                        x: Math.random() * w,
                        y: Math.random() * h,
                        vx: (Math.random() - 0.5) * 20,
                        vy: (Math.random() - 0.5) * 20,
                        r: Math.random() * 2.5 + 1.5,
                        fase: Math.random() * Math.PI * 2,
                        vFase: Math.random() * 2 + 1,
                        col: ['#a6e3a1', '#f9e2af', '#89dceb'][i % 3]
                    });
                }
                return { luciernagas };
            },
            update: (dt, w, h, mouse, state) => {
                const luc = state.luciernagas;
                for (let i = 0; i < luc.length; i++) {
                    const l = luc[i];
                    l.x += l.vx * dt + Math.sin(l.fase) * 8 * dt;
                    l.y += l.vy * dt + Math.cos(l.fase) * 8 * dt;
                    l.fase += l.vFase * dt;

                    if (l.x < 0) l.x = w;
                    else if (l.x > w) l.x = 0;
                    if (l.y < 0) l.y = h;
                    else if (l.y > h) l.y = 0;
                }
            },
            render: (ctx, w, h, dt, mouse, state) => {
                ctx.clearRect(0, 0, w, h);
                const luc = state.luciernagas;
                for (let i = 0; i < luc.length; i++) {
                    const l = luc[i];
                    const alfa = Math.max(0.15, (Math.sin(l.fase) * 0.5 + 0.5) * 0.85);

                    ctx.fillStyle = l.col;
                    ctx.shadowColor = l.col;
                    ctx.shadowBlur = 12 * alfa;
                    ctx.beginPath();
                    ctx.arc(l.x, l.y, l.r, 0, Math.PI * 2);
                    ctx.fill();
                }
            }
        });

        // -------------------------------------------------------------
        // 11. VÓRTICE DIMENSIONAL HIPNÓTICO
        // -------------------------------------------------------------
        this.registrarEfecto('tunel_vortex', {
            nombre: 'Vórtice Dimensional',
            icono: 'fa-compact-disc',
            desc: 'Anillos concéntricos giratorios que crean una sensación de túnel infinito.',
            init: () => ({ rotacion: 0 }),
            update: (dt, w, h, mouse, state) => {
                state.rotacion += dt * 0.8;
            },
            render: (ctx, w, h, dt, mouse, state) => {
                ctx.clearRect(0, 0, w, h);
                const cx = w / 2;
                const cy = h / 2;
                const maxR = Math.hypot(cx, cy);

                ctx.save();
                ctx.translate(cx, cy);
                ctx.rotate(state.rotacion);

                for (let r = 20; r < maxR; r += 35) {
                    const alfa = Math.max(0.05, 0.25 - (r / maxR) * 0.2);
                    ctx.strokeStyle = `rgba(137, 180, 250, ${alfa})`;
                    ctx.lineWidth = 1.2;
                    ctx.beginPath();
                    ctx.arc(0, 0, r, 0, Math.PI * 2);
                    ctx.stroke();

                    // Pequeños rayos radiales
                    for (let a = 0; a < Math.PI * 2; a += Math.PI / 4) {
                        ctx.beginPath();
                        ctx.moveTo(Math.cos(a) * (r - 10), Math.sin(a) * (r - 10));
                        ctx.lineTo(Math.cos(a) * r, Math.sin(a) * r);
                        ctx.stroke();
                    }
                }
                ctx.restore();
            }
        });

        // -------------------------------------------------------------
        // 12. DEGRADADO LÍQUIDO EN MOVIMIENTO (Fallback Canvas)
        // -------------------------------------------------------------
        this.registrarEfecto('ondas_gradiente', {
            nombre: 'Degradado Líquido Fluido',
            icono: 'fa-wand-magic-sparkles',
            desc: 'Transición continua de gradientes suaves con armonía de colores del tema.',
            init: () => ({ fase: 0 }),
            update: (dt, w, h, mouse, state) => {
                state.fase += dt * 0.5;
            },
            render: (ctx, w, h, dt, mouse, state) => {
                const f = state.fase;
                const x1 = Math.sin(f) * (w * 0.4) + (w * 0.5);
                const y1 = Math.cos(f * 0.7) * (h * 0.4) + (h * 0.5);
                const x2 = Math.cos(f * 0.5) * (w * 0.4) + (w * 0.5);
                const y2 = Math.sin(f * 0.8) * (h * 0.4) + (h * 0.5);

                const grad = ctx.createLinearGradient(x1, y1, x2, y2);
                grad.addColorStop(0, 'rgba(24, 5, 46, 0.95)');
                grad.addColorStop(0.35, 'rgba(30, 30, 46, 0.95)');
                grad.addColorStop(0.7, 'rgba(20, 89, 107, 0.95)');
                grad.addColorStop(1, 'rgba(6, 11, 20, 0.95)');

                ctx.fillStyle = grad;
                ctx.fillRect(0, 0, w, h);
            }
        });

        // -------------------------------------------------------------
        // 13. ATRACTOR CAÓTICO DE LORENZ 3D
        // -------------------------------------------------------------
        this.registrarEfecto('atractor_lorentz', {
            nombre: 'Atractor Caótico de Lorenz 3D',
            icono: 'fa-infinity',
            desc: 'Ecuaciones diferenciales trazando la mística mariposa del caos matemático en 3D.',
            init: () => {
                const puntos = [];
                let x = 0.1, y = 0, z = 0;
                const sigma = 10, rho = 28, beta = 8 / 3, dtMath = 0.008;
                for (let i = 0; i < 900; i++) {
                    const dx = sigma * (y - x) * dtMath;
                    const dy = (x * (rho - z) - y) * dtMath;
                    const dz = (x * y - beta * z) * dtMath;
                    x += dx; y += dy; z += dz;
                    puntos.push({ x, y, z });
                }
                return { puntos, angulo: 0 };
            },
            update: (dt, w, h, mouse, state) => {
                state.angulo += dt * 0.4;
            },
            render: (ctx, w, h, dt, mouse, state) => {
                ctx.fillStyle = 'rgba(10, 8, 20, 0.25)';
                ctx.fillRect(0, 0, w, h);

                const cx = w / 2;
                const cy = h / 2;
                const pts = state.puntos;
                const cosA = Math.cos(state.angulo);
                const sinA = Math.sin(state.angulo);
                const escala = Math.min(w, h) / 75;

                ctx.lineWidth = 1.5;
                ctx.shadowBlur = 10;

                for (let i = 1; i < pts.length; i++) {
                    const p1 = pts[i - 1];
                    const p2 = pts[i];

                    // Rotación en eje Y
                    const x1Rot = p1.x * cosA - p1.z * sinA;
                    const z1Rot = p1.x * sinA + p1.z * cosA;
                    const x2Rot = p2.x * cosA - p2.z * sinA;
                    const z2Rot = p2.x * sinA + p2.z * cosA;

                    const sx1 = cx + x1Rot * escala;
                    const sy1 = cy + (p1.y - 25) * escala;
                    const sx2 = cx + x2Rot * escala;
                    const sy2 = cy + (p2.y - 25) * escala;

                    const hue = (i * 0.4 + state.angulo * 40) % 360;
                    ctx.strokeStyle = `hsla(${hue}, 90%, 65%, 0.55)`;
                    ctx.shadowColor = `hsla(${hue}, 90%, 65%, 0.8)`;

                    ctx.beginPath();
                    ctx.moveTo(sx1, sy1);
                    ctx.lineTo(sx2, sy2);
                    ctx.stroke();
                }
            }
        });

        // -------------------------------------------------------------
        // 14. AGUJERO NEGRO INTERSTELLAR & DISCO DE ACRECIÓN
        // -------------------------------------------------------------
        this.registrarEfecto('agujero_negro_interstellar', {
            nombre: 'Agujero Negro Interstellar',
            icono: 'fa-circle-notch',
            desc: 'Disco de acreción gravitacional con curvatura del espaciotiempo e interacción orbital.',
            init: () => {
                const particulas = [];
                for (let i = 0; i < 180; i++) {
                    const radio = Math.random() * 220 + 50;
                    particulas.push({
                        radio: radio,
                        angulo: Math.random() * Math.PI * 2,
                        velocidad: (350 / Math.sqrt(radio)) * (Math.random() * 0.2 + 0.9),
                        tam: Math.random() * 2.5 + 1.2,
                        hue: Math.random() * 45 + 15 // Naranja a oro brillante
                    });
                }
                return { particulas, rotacion: 0 };
            },
            update: (dt, w, h, mouse, state) => {
                const pts = state.particulas;
                for (let i = 0; i < pts.length; i++) {
                    const p = pts[i];
                    p.angulo += (p.velocidad * 0.003) * dt * 60;
                }
            },
            render: (ctx, w, h, dt, mouse, state) => {
                ctx.fillStyle = 'rgba(5, 5, 12, 0.28)';
                ctx.fillRect(0, 0, w, h);

                const cx = mouse.activo ? (w / 2 + (mouse.x - w / 2) * 0.15) : (w / 2);
                const cy = mouse.activo ? (h / 2 + (mouse.y - h / 2) * 0.15) : (h / 2);

                // Halo exterior brillante de lentes gravitacionales
                const gradHalo = ctx.createRadialGradient(cx, cy, 35, cx, cy, 260);
                gradHalo.addColorStop(0, 'rgba(255, 120, 0, 0.25)');
                gradHalo.addColorStop(0.4, 'rgba(255, 60, 150, 0.12)');
                gradHalo.addColorStop(1, 'rgba(0, 0, 0, 0)');
                ctx.fillStyle = gradHalo;
                ctx.beginPath();
                ctx.arc(cx, cy, 260, 0, Math.PI * 2);
                ctx.fill();

                // Partículas del disco de acreción en elipse inclinada
                const pts = state.particulas;
                for (let i = 0; i < pts.length; i++) {
                    const p = pts[i];
                    const px = cx + Math.cos(p.angulo) * p.radio;
                    const py = cy + Math.sin(p.angulo) * (p.radio * 0.38);

                    const alfa = Math.sin(p.angulo) > 0 ? 0.9 : 0.4;
                    ctx.fillStyle = `hsla(${p.hue}, 100%, 65%, ${alfa})`;
                    ctx.shadowColor = `hsla(${p.hue}, 100%, 60%, 1)`;
                    ctx.shadowBlur = 8;
                    ctx.beginPath();
                    ctx.arc(px, py, p.tam, 0, Math.PI * 2);
                    ctx.fill();
                }

                // Horizonte de Sucesos central (Negro absoluto impenetrable)
                ctx.shadowBlur = 25;
                ctx.shadowColor = 'rgba(255, 180, 50, 0.9)';
                ctx.fillStyle = '#000000';
                ctx.beginPath();
                ctx.arc(cx, cy, 46, 0, Math.PI * 2);
                ctx.fill();

                // Anillo fotónico ultrafino
                ctx.strokeStyle = '#ffffff';
                ctx.lineWidth = 1.8;
                ctx.stroke();
            }
        });

        // -------------------------------------------------------------
        // 15. MICELIO ALIENÍGENA BIOLUMINISCENTE
        // -------------------------------------------------------------
        this.registrarEfecto('red_micelio_fungico', {
            nombre: 'Micelio Alienígena Bioluminiscente',
            icono: 'fa-dna',
            desc: 'Ramificación biológica de hifas fosforescentes con emisión de esporas de plasma.',
            init: () => {
                const nodos = [];
                for (let i = 0; i < 55; i++) {
                    nodos.push({
                        x: Math.random() * (window.innerWidth || 800),
                        y: Math.random() * (window.innerHeight || 600),
                        vx: (Math.random() - 0.5) * 18,
                        vy: (Math.random() - 0.5) * 18,
                        pulso: Math.random() * Math.PI * 2,
                        r: Math.random() * 3 + 2,
                        col: ['#00ffc2', '#78ffd6', '#a855f7', '#00d4ff'][i % 4]
                    });
                }
                return { nodos };
            },
            update: (dt, w, h, mouse, state) => {
                const nds = state.nodos;
                for (let i = 0; i < nds.length; i++) {
                    const n = nds[i];
                    n.x += n.vx * dt;
                    n.y += n.vy * dt;
                    n.pulso += dt * 2.5;

                    if (n.x < 0) n.x = w;
                    else if (n.x > w) n.x = 0;
                    if (n.y < 0) n.y = h;
                    else if (n.y > h) n.y = 0;

                    // Repulsión sutil con mouse
                    if (mouse.activo) {
                        const dx = n.x - mouse.x;
                        const dy = n.y - mouse.y;
                        const dist = Math.hypot(dx, dy);
                        if (dist < 120 && dist > 1) {
                            n.x += (dx / dist) * 40 * dt;
                            n.y += (dy / dist) * 40 * dt;
                        }
                    }
                }
            },
            render: (ctx, w, h, dt, mouse, state) => {
                ctx.clearRect(0, 0, w, h);
                const nds = state.nodos;

                // Conexiones de hifas
                for (let i = 0; i < nds.length; i++) {
                    for (let j = i + 1; j < nds.length; j++) {
                        const a = nds[i];
                        const b = nds[j];
                        const dist = Math.hypot(a.x - b.x, a.y - b.y);
                        if (dist < 135) {
                            const alfa = (1 - dist / 135) * 0.45;
                            ctx.strokeStyle = `rgba(0, 255, 194, ${alfa})`;
                            ctx.lineWidth = 1.2;
                            ctx.beginPath();
                            ctx.moveTo(a.x, a.y);
                            ctx.lineTo(b.x, b.y);
                            ctx.stroke();
                        }
                    }
                }

                // Esporas emisoras
                for (let i = 0; i < nds.length; i++) {
                    const n = nds[i];
                    const escala = Math.sin(n.pulso) * 0.4 + 1.0;
                    ctx.fillStyle = n.col;
                    ctx.shadowColor = n.col;
                    ctx.shadowBlur = 12;
                    ctx.beginPath();
                    ctx.arc(n.x, n.y, n.r * escala, 0, Math.PI * 2);
                    ctx.fill();
                }
            }
        });

        // -------------------------------------------------------------
        // 16. GLITCH CUÁNTICO CYBERPUNK
        // -------------------------------------------------------------
        this.registrarEfecto('glitch_cyber_digital', {
            nombre: 'Glitch Cuántico Cyberpunk',
            icono: 'fa-bug',
            desc: 'Bloques de datos fragmentados y aberración cuántica con decodificación en tiempo real.',
            init: () => {
                return { bloques: [], timer: 0 };
            },
            update: (dt, w, h, mouse, state) => {
                state.timer += dt;
                if (state.timer > 0.08) {
                    state.timer = 0;
                    state.bloques = [];
                    const cantidad = Math.floor(Math.random() * 12) + 6;
                    for (let i = 0; i < cantidad; i++) {
                        state.bloques.push({
                            x: Math.random() * w,
                            y: Math.random() * h,
                            w: Math.random() * 180 + 30,
                            h: Math.random() * 14 + 2,
                            col: ['rgba(255,0,127,0.4)', 'rgba(0,255,255,0.4)', 'rgba(0,255,102,0.4)', 'rgba(255,230,0,0.35)'][i % 4]
                        });
                    }
                }
            },
            render: (ctx, w, h, dt, mouse, state) => {
                ctx.fillStyle = 'rgba(10, 5, 20, 0.2)';
                ctx.fillRect(0, 0, w, h);

                const bq = state.bloques;
                for (let i = 0; i < bq.length; i++) {
                    const b = bq[i];
                    ctx.fillStyle = b.col;
                    ctx.fillRect(b.x, b.y, b.w, b.h);
                }

                // Líneas de ruido analógico
                ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';
                ctx.lineWidth = 1;
                for (let y = 0; y < h; y += 8) {
                    ctx.beginPath();
                    ctx.moveTo(0, y);
                    ctx.lineTo(w, y);
                    ctx.stroke();
                }
            }
        });

        // -------------------------------------------------------------
        // 17. HIPERCUBO 4D TESSERACT
        // -------------------------------------------------------------
        this.registrarEfecto('hipercubo_4d_tesseract', {
            nombre: 'Hipercubo 4D Tesseract',
            icono: 'fa-cube',
            desc: 'Proyección matemática tridimensional de un teseracto de 4 dimensiones rotando en el hiperespacio.',
            init: () => {
                const vertices = [];
                for (let x = -1; x <= 1; x += 2) {
                    for (let y = -1; y <= 1; y += 2) {
                        for (let z = -1; z <= 1; z += 2) {
                            for (let w = -1; w <= 1; w += 2) {
                                vertices.push([x, y, z, w]);
                            }
                        }
                    }
                }
                const aristas = [];
                for (let i = 0; i < 16; i++) {
                    for (let j = i + 1; j < 16; j++) {
                        let diff = 0;
                        for (let k = 0; k < 4; k++) {
                            if (vertices[i][k] !== vertices[j][k]) diff++;
                        }
                        if (diff === 1) aristas.push([i, j]);
                    }
                }
                return { vertices, aristas, angulo: 0 };
            },
            update: (dt, w, h, mouse, state) => {
                state.angulo += dt * 0.6;
            },
            render: (ctx, w, h, dt, mouse, state) => {
                ctx.clearRect(0, 0, w, h);
                const cx = w / 2;
                const cy = h / 2;
                const escalaBase = Math.min(w, h) * 0.32;
                const a = state.angulo;

                const cosA = Math.cos(a);
                const sinA = Math.sin(a);
                const cosB = Math.cos(a * 0.7);
                const sinB = Math.sin(a * 0.7);

                // Proyección 4D -> 3D -> 2D
                const proyectados = state.vertices.map(v => {
                    let [x, y, z, w_coord] = v;

                    // Rotación en plano XW
                    let x1 = x * cosA - w_coord * sinA;
                    let w1 = x * sinA + w_coord * cosA;

                    // Rotación en plano YZ
                    let y1 = y * cosB - z * sinB;
                    let z1 = y * sinB + z * cosB;

                    // Proyección perspectiva 4D -> 3D
                    const dist4D = 2.5;
                    const factor4D = 1 / (dist4D - w1);
                    let x3D = x1 * factor4D;
                    let y3D = y1 * factor4D;
                    let z3D = z1 * factor4D;

                    // Proyección perspectiva 3D -> 2D
                    const dist3D = 3.0;
                    const factor3D = 1 / (dist3D - z3D);

                    return [
                        cx + x3D * factor3D * escalaBase,
                        cy + y3D * factor3D * escalaBase,
                        w1
                    ];
                });

                // Dibujar aristas con resplandor cian/magenta
                ctx.lineWidth = 1.5;
                ctx.shadowBlur = 10;

                for (let i = 0; i < state.aristas.length; i++) {
                    const [i1, i2] = state.aristas[i];
                    const p1 = proyectados[i1];
                    const p2 = proyectados[i2];

                    const wProm = (p1[2] + p2[2]) / 2;
                    const alfa = Math.max(0.2, (wProm + 1) * 0.45);

                    ctx.strokeStyle = `rgba(137, 180, 250, ${alfa})`;
                    ctx.shadowColor = '#cba6f7';

                    ctx.beginPath();
                    ctx.moveTo(p1[0], p1[1]);
                    ctx.lineTo(p2[0], p2[1]);
                    ctx.stroke();
                }

                // Dibujar vértices
                ctx.fillStyle = '#00ffff';
                ctx.shadowColor = '#00ffff';
                ctx.shadowBlur = 8;
                for (let i = 0; i < proyectados.length; i++) {
                    const p = proyectados[i];
                    ctx.beginPath();
                    ctx.arc(p[0], p[1], 3, 0, Math.PI * 2);
                    ctx.fill();
                }
            }
        });

        // -------------------------------------------------------------
        // 18. ROBOT MATRIX ARTILLERO (MECANOGRAFÍA REACTIVA Y RASTREO)
        // -------------------------------------------------------------
        // -------------------------------------------------------------
        // 18. ROBOT MATRIX ARTILLERO (MECANOGRAFÍA REACTIVA Y RASTREO)
        // -------------------------------------------------------------
        this.registrarEfecto('robot_matrix', {
            nombre: 'Robot Matrix Artillero',
            icono: 'fa-robot',
            desc: 'Titán Mecha cibernético en arte ASCII hiperrealista que dispara caracteres de código únicamente al escribir.',
            init: (canvas, w, h, densidad) => {
                const chars = '0123456789ABCDEFｦｱｳｴｵｶｷｹｺｻｼｽｾｿﾀﾂﾃﾅﾆﾇﾈﾊﾋﾎﾏﾐﾑﾒﾓﾔﾕﾗﾘﾜλΩ{}[]=>/*#$!+-%';
                
                // Lluvia Matrix de fondo ultra ligera
                const numLluvia = Math.floor(18 * densidad);
                const gotas = [];
                for (let i = 0; i < numLluvia; i++) {
                    gotas.push({
                        x: (i / numLluvia) * w + (Math.random() - 0.5) * 30,
                        y: Math.random() * -h,
                        vel: Math.random() * 120 + 90,
                        longitud: Math.floor(Math.random() * 8 + 6),
                        chars: Array.from({ length: 12 }, () => chars[Math.floor(Math.random() * chars.length)]),
                        cambioTimer: 0
                    });
                }

                // Estado del Robot Cibernético
                const robot = {
                    x: w * 0.5,
                    y: h * 0.72,
                    escala: Math.max(0.65, Math.min(1.3, Math.min(w, h) / 780)),
                    anguloTorretaL: -Math.PI / 4,
                    anguloTorretaR: -Math.PI * 3 / 4,
                    anguloCabeza: 0,
                    recoilL: 0,
                    recoilR: 0,
                    muzzleL: 0,
                    muzzleR: 0,
                    ultimoCanonFuego: 'L',
                    targetX: -9999,
                    targetY: -9999,
                    apuntandoActivo: false
                };

                return {
                    chars,
                    gotas,
                    robot,
                    proyectiles: [],
                    impactos: [],
                    tiempoGlobal: 0
                };
            },
            onResize: (w, h, state) => {
                if (!state || !state.robot) return;
                state.robot.x = w * 0.5;
                state.robot.y = h * 0.72;
                state.robot.escala = Math.max(0.65, Math.min(1.3, Math.min(w, h) / 780));
            },
            onDisparo: (targetX, targetY, char, state) => {
                if (!state || !state.robot) return;
                const r = state.robot;
                r.targetX = targetX;
                r.targetY = targetY;
                r.apuntandoActivo = true;

                const escala = r.escala || 1.0;
                const canonL_x = r.x - 120 * escala;
                const canonL_y = r.y - 30 * escala;
                const canonR_x = r.x + 120 * escala;
                const canonR_y = r.y - 30 * escala;

                // Alternar entre cañones
                const usarL = (r.ultimoCanonFuego === 'R');
                r.ultimoCanonFuego = usarL ? 'L' : 'R';

                const origenX = usarL ? canonL_x : canonR_x;
                const origenY = usarL ? canonL_y : canonR_y;

                if (usarL) {
                    r.recoilL = 16 * escala;
                    r.muzzleL = 1.0;
                } else {
                    r.recoilR = 16 * escala;
                    r.muzzleR = 1.0;
                }

                // Generar proyectil láser de código
                const dx = targetX - origenX;
                const dy = targetY - origenY;
                const dist = Math.hypot(dx, dy) || 1;
                const vel = 1750; // Ultra rápido para respuesta instantánea

                const tokensFallback = ['def', 'class', 'import', 'return', 'async', '=>', 'λ', '1', '0', '{}', 'fn', 'let', 'const'];
                const tokenElegido = (char && char.trim() && char.length === 1) ? char.trim() : tokensFallback[Math.floor(Math.random() * tokensFallback.length)];

                state.proyectiles.push({
                    x: origenX,
                    y: origenY,
                    vx: (dx / dist) * vel,
                    vy: (dy / dist) * vel,
                    targetX,
                    targetY,
                    distTotal: dist,
                    distRecorrida: 0,
                    char: tokenElegido,
                    color: usarL ? '#00ff66' : '#00ffff',
                    rot: Math.atan2(dy, dx),
                    vida: 0.9
                });
            },
            update: (dt, w, h, mouse, state, audio, cursorTexto) => {
                state.tiempoGlobal += dt;
                const r = state.robot;
                const boostVel = (audio && audio.reactivo) ? audio.boostVelocidad : 1.0;

                // Determinar objetivo: solo cursor de texto o mouse activo
                let objetivoX = r.targetX;
                let objetivoY = r.targetY;

                if (cursorTexto && cursorTexto.activo && (performance.now() - cursorTexto.ultimoDisparo < 3000)) {
                    objetivoX = cursorTexto.targetX;
                    objetivoY = cursorTexto.targetY;
                    r.apuntandoActivo = true;
                } else if (mouse && mouse.activo && (performance.now() - mouse.ultimoMov < 2000)) {
                    objetivoX = mouse.x;
                    objetivoY = mouse.y;
                    r.apuntandoActivo = true;
                } else {
                    // Posición de reposo al frente
                    objetivoX = w * 0.5;
                    objetivoY = h * 0.25;
                    r.apuntandoActivo = false;
                }

                r.targetX = objetivoX;
                r.targetY = objetivoY;

                const escala = r.escala || 1.0;
                const canonL_x = r.x - 120 * escala;
                const canonL_y = r.y - 30 * escala;
                const canonR_x = r.x + 120 * escala;
                const canonR_y = r.y - 30 * escala;

                // Suavizar rotación de cañones
                const angDeseadoL = Math.atan2(objetivoY - canonL_y, objetivoX - canonL_x);
                const angDeseadoR = Math.atan2(objetivoY - canonR_y, objetivoX - canonR_x);
                const angDeseadoCabeza = Math.atan2(objetivoY - (r.y - 110 * escala), objetivoX - r.x);

                r.anguloTorretaL += (angDeseadoL - r.anguloTorretaL) * Math.min(1.0, dt * 18);
                r.anguloTorretaR += (angDeseadoR - r.anguloTorretaR) * Math.min(1.0, dt * 18);
                r.anguloCabeza += (angDeseadoCabeza - r.anguloCabeza) * Math.min(1.0, dt * 12);

                // Recuperación de retroceso
                r.recoilL = Math.max(0, r.recoilL - dt * 60 * escala);
                r.recoilR = Math.max(0, r.recoilR - dt * 60 * escala);
                r.muzzleL = Math.max(0, r.muzzleL - dt * 8);
                r.muzzleR = Math.max(0, r.muzzleR - dt * 8);

                // Lluvia Matrix ligera
                for (let i = 0; i < state.gotas.length; i++) {
                    const g = state.gotas[i];
                    g.y += g.vel * dt * boostVel;
                    g.cambioTimer += dt;
                    if (g.cambioTimer > 0.2) {
                        g.cambioTimer = 0;
                        const idx = Math.floor(Math.random() * g.chars.length);
                        g.chars[idx] = state.chars[Math.floor(Math.random() * state.chars.length)];
                    }
                    if (g.y > h + 100) {
                        g.y = Math.random() * -100;
                        g.x = Math.random() * w;
                    }
                }

                // Actualizar proyectiles balísticos
                for (let i = state.proyectiles.length - 1; i >= 0; i--) {
                    const p = state.proyectiles[i];
                    p.x += p.vx * dt;
                    p.y += p.vy * dt;
                    p.distRecorrida += Math.hypot(p.vx * dt, p.vy * dt);
                    p.vida -= dt;

                    const dx = p.targetX - p.x;
                    const dy = p.targetY - p.y;
                    const distRestante = Math.hypot(dx, dy);

                    if (distRestante < 35 || p.distRecorrida >= p.distTotal || p.vida <= 0) {
                        const impX = (distRestante < 35) ? p.x : p.targetX;
                        const impY = (distRestante < 35) ? p.y : p.targetY;

                        // Chispas de impacto puramente ASCII
                        const fragTokens = ['*', '+', 'x', '░', '▓', '·', '•'];
                        const fragmentos = [];
                        for (let f = 0; f < 8; f++) {
                            const ang = (Math.PI * 2 * f) / 8 + (Math.random() - 0.5) * 0.4;
                            const spd = Math.random() * 120 + 50;
                            fragmentos.push({
                                x: impX,
                                y: impY,
                                vx: Math.cos(ang) * spd,
                                vy: Math.sin(ang) * spd,
                                char: fragTokens[Math.floor(Math.random() * fragTokens.length)],
                                color: p.color
                            });
                        }

                        state.impactos.push({
                            x: impX,
                            y: impY,
                            char: p.char,
                            vida: 0.28,
                            vidaMax: 0.28,
                            fragmentos
                        });

                        state.proyectiles.splice(i, 1);
                    }
                }

                // Actualizar impactos
                for (let i = state.impactos.length - 1; i >= 0; i--) {
                    const imp = state.impactos[i];
                    imp.vida -= dt;

                    for (let f = 0; f < imp.fragmentos.length; f++) {
                        const fr = imp.fragmentos[f];
                        fr.x += fr.vx * dt;
                        fr.y += fr.vy * dt;
                        fr.vx *= 0.88;
                        fr.vy *= 0.88;
                    }

                    if (imp.vida <= 0) {
                        state.impactos.splice(i, 1);
                    }
                }
            },
            render: (ctx, w, h, dt, mouse, state, time, audio, cursorTexto) => {
                ctx.clearRect(0, 0, w, h);

                const r = state.robot;
                const escala = r.escala || 1.0;
                const bass = (audio && audio.reactivo) ? audio.energiaBass : 0;

                ctx.save();

                // --- 1. Lluvia Matrix ligera de fondo ---
                ctx.font = '11px "Fira Code", monospace';
                ctx.textAlign = 'center';
                for (let i = 0; i < state.gotas.length; i++) {
                    const g = state.gotas[i];
                    for (let j = 0; j < g.longitud; j++) {
                        const yChar = g.y - j * 14;
                        if (yChar < -20 || yChar > h + 20) continue;
                        const alpha = (1 - j / g.longitud) * 0.28;
                        ctx.fillStyle = j === 0 ? 'rgba(255, 255, 255, 0.7)' : `rgba(0, 255, 102, ${alpha})`;
                        ctx.fillText(g.chars[j % g.chars.length] || '0', g.x, yChar);
                    }
                }

                // --- 2. Líneas láser guía hacia el cursor (Solo cuando apunta) ---
                const canonL_x = r.x - 120 * escala;
                const canonL_y = r.y - 30 * escala;
                const canonR_x = r.x + 120 * escala;
                const canonR_y = r.y - 30 * escala;

                if (r.apuntandoActivo && r.targetX > 0) {
                    ctx.strokeStyle = `rgba(0, 255, 150, ${0.15 + bass * 0.2})`;
                    ctx.lineWidth = 1;
                    ctx.setLineDash([4, 6]);
                    ctx.beginPath();
                    ctx.moveTo(canonL_x, canonL_y);
                    ctx.lineTo(r.targetX, r.targetY);
                    ctx.moveTo(canonR_x, canonR_y);
                    ctx.lineTo(r.targetX, r.targetY);
                    ctx.stroke();
                    ctx.setLineDash([]);
                }

                // --- 3. Titán Mecha Central en Arte ASCII Hiperrealista ---
                ctx.save();
                ctx.translate(r.x, r.y);
                ctx.scale(escala, escala);
                ctx.textAlign = 'center';
                ctx.font = 'bold 12px "Fira Code", monospace';

                // A. Chasis Inferior y Blindaje Hidráulico
                ctx.fillStyle = 'rgba(0, 255, 136, 0.55)';
                ctx.fillText('      ╔═════════════════════════════════════════════╗      ', 0, 110);
                ctx.fillText('  ╔═══╝ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ╚═══╗  ', 0, 96);
                ctx.fillText('  ║ █║▓▓▓▓▓▓▓▓ [ TITAN-MECHA: MK-VII ] ▓▓▓▓▓▓▓▓║█ ║  ', 0, 82);
                ctx.fillText('  ╚═══╦═════════════════════════════════════════╦═══╝  ', 0, 68);

                // B. Torso Principal, Conduits y Placas de Blindaje
                ctx.fillStyle = 'rgba(0, 255, 136, 0.85)';
                ctx.fillText('     / ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ \\     ', 0, 52);
                ctx.fillText('    | █▓▓ [CORE:ONLINE] ▓▓▓▓▓▓▓▓▓▓▓ [PWR:100%] ▓▓█ |    ', 0, 38);
                ctx.fillText('    | █║ /// [░░░░░░]  {λ} QUANTUM {Ω}  [░░░░░░] \\\\\\ ║█ |    ', 0, 24);
                ctx.fillText('    | █║ /// ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ \\\\\\ ║█ |    ', 0, 10);
                ctx.fillText('    | █║═══════════════════════════════════════║█ |    ', 0, -4);
                ctx.fillText('     \\ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ /     ', 0, -18);
                ctx.fillText('      \'=========================================\'      ', 0, -32);

                // C. Cabeza / Yelmo Táctico Mecha con Antenas y Visor
                ctx.save();
                ctx.translate(0, -68);
                ctx.rotate(r.anguloCabeza * 0.2);

                ctx.fillStyle = 'rgba(0, 255, 200, 0.95)';
                ctx.fillText('           /\\                            /\\           ', 0, -38);
                ctx.fillText('          / /\\                          /\\ \\          ', 0, -26);
                ctx.fillText('         / /  \\   .----------------.   /  \\ \\         ', 0, -14);
                ctx.fillText('        / / /\\ \\ / ░░░░░░░░░░░░░░░░ \\ / /\\ \\ \\        ', 0, -2);
                ctx.fillText('       ( ( (  \\ \\| █║████████████║█ |/ /  ) ) )       ', 0, 10);
                ctx.fillText('        \\ \\ \\  \\/| [==[══VISOR══]==] |\\/  / / /        ', 0, 22);
                ctx.fillText('         \'---\'   \\ ░░░░░░░░░░░░░░░░ /   \'---\'         ', 0, 34);
                ctx.fillText('                  \'----------------\'                  ', 0, 46);

                // Visor óptico luminoso
                const ojoShift = Math.sin(r.anguloCabeza) * 8;
                ctx.fillStyle = '#00ffff';
                ctx.fillText('==[►►]====', ojoShift, 22);

                ctx.restore();
                ctx.restore(); // Fin escala mecha

                // --- 4. Cañones de Artillería Articulados en ASCII ---
                const renderCanon = (cx, cy, angulo, recoil, muzzle, isLeft) => {
                    ctx.save();
                    ctx.translate(cx, cy);
                    ctx.rotate(angulo);
                    ctx.translate(-recoil, 0);

                    ctx.font = 'bold 12px "Fira Code", monospace';
                    ctx.textAlign = 'left';

                    // Cañón de asalto
                    ctx.fillStyle = 'rgba(0, 255, 136, 0.9)';
                    ctx.fillText('╔══[TURRET]══╦══════════════════►►►', -20, -2);
                    ctx.fillStyle = '#00ffff';
                    ctx.fillText('║ ▓▓▓▓▓▓▓▓▓▓ ║====[PLASMA-BURST]===►', -20, 10);
                    ctx.fillStyle = 'rgba(0, 255, 136, 0.9)';
                    ctx.fillText('╚════════════╩══════════════════►►►', -20, 22);

                    // Muzzle flash en ASCII
                    if (muzzle > 0.1) {
                        ctx.fillStyle = '#ffffff';
                        ctx.fillText('✦ █▓▒░ >>', 180, 10);
                    }

                    ctx.restore();
                };

                renderCanon(canonL_x, canonL_y, r.anguloTorretaL, r.recoilL, r.muzzleL, true);
                renderCanon(canonR_x, canonR_y, r.anguloTorretaR, r.recoilR, r.muzzleR, false);

                // --- 5. Proyectiles Balísticos de Código (Sin círculos) ---
                for (let i = 0; i < state.proyectiles.length; i++) {
                    const p = state.proyectiles[i];

                    ctx.save();
                    ctx.translate(p.x, p.y);
                    ctx.rotate(p.rot);
                    ctx.font = 'bold 13px "Fira Code", monospace';
                    ctx.textAlign = 'center';
                    ctx.fillStyle = p.color;
                    ctx.fillText(`==[ ${p.char} ]====►►`, 0, 4);
                    ctx.restore();
                }

                // --- 6. Impactos en ASCII puro en el punto de mecanografía ---
                for (let i = 0; i < state.impactos.length; i++) {
                    const imp = state.impactos[i];
                    const alpha = (imp.vida / imp.vidaMax);

                    ctx.save();
                    ctx.textAlign = 'center';
                    ctx.font = 'bold 12px "Fira Code", monospace';

                    // Token central que se desvanece
                    ctx.fillStyle = `rgba(255, 255, 255, ${alpha})`;
                    ctx.fillText(`[${imp.char}]`, imp.x, imp.y);

                    // Chispas ASCII
                    for (let f = 0; f < imp.fragmentos.length; f++) {
                        const fr = imp.fragmentos[f];
                        ctx.fillStyle = `rgba(0, 255, 200, ${alpha})`;
                        ctx.fillText(fr.char, fr.x, fr.y);
                    }

                    ctx.restore();
                }

                // --- 7. Mira HUD Táctica en el Caret (Solo ASCII) ---
                if (r.apuntandoActivo && r.targetX > 0) {
                    ctx.save();
                    ctx.translate(r.targetX, r.targetY);
                    ctx.font = 'bold 11px "Fira Code", monospace';
                    ctx.textAlign = 'center';
                    ctx.fillStyle = 'rgba(0, 255, 200, 0.85)';
                    ctx.fillText('< + >', 0, 4);
                    ctx.font = '9px "Fira Code", monospace';
                    ctx.fillText('[TARGET: LOCKED]', 0, -10);
                    ctx.restore();
                }

                ctx.restore();
            }
        });

        // -------------------------------------------------------------
        // 19. MONOLITO CÓSMICO 3D (ASCII Obelisk & Geometric Orbit)
        // -------------------------------------------------------------
        this.registrarEfecto('ascii_monolito_cosmico', {
            nombre: 'Monolito Cósmico ASCII',
            icono: 'fa-cubes-stacked',
            desc: 'Obelisco tridimensional en arte ASCII con sombreado de bloques dithered y anillos de runas giratorios.',
            init: (canvas, w, h, densidad) => {
                const estrellas = [];
                const cantEstrellas = Math.floor(45 * densidad);
                for (let i = 0; i < cantEstrellas; i++) {
                    estrellas.push({
                        x: Math.random() * w,
                        y: Math.random() * h,
                        char: ['·', '°', '+', '˙', '•'][Math.floor(Math.random() * 5)],
                        alfa: Math.random() * 0.4 + 0.2,
                        parpadeoVel: Math.random() * 2 + 1
                    });
                }
                return { angulo: 0, tiempo: 0, estrellas };
            },
            update: (dt, w, h, mouse, state, audio) => {
                state.tiempo += dt;
                const boost = (audio && audio.reactivo) ? (1 + audio.energiaBass * 1.5) : 1.0;
                state.angulo += dt * 0.75 * boost;
            },
            render: (ctx, w, h, dt, mouse, state, time, audio) => {
                ctx.clearRect(0, 0, w, h);
                const cx = w * 0.5;
                const cy = h * 0.5;
                const bass = (audio && audio.reactivo) ? audio.energiaBass : 0;
                const a = state.angulo;

                ctx.save();

                // Estrellas de fondo
                ctx.font = '12px "Fira Code", monospace';
                for (let i = 0; i < state.estrellas.length; i++) {
                    const e = state.estrellas[i];
                    const alfa = e.alfa + Math.sin(state.tiempo * e.parpadeoVel + i) * 0.15;
                    ctx.fillStyle = `rgba(218, 187, 120, ${Math.max(0.1, alfa)})`;
                    ctx.fillText(e.char, e.x, e.y);
                }

                // Horizonte Geométrico
                ctx.strokeStyle = 'rgba(218, 187, 120, 0.12)';
                ctx.lineWidth = 1;
                ctx.beginPath();
                ctx.moveTo(0, cy + 180);
                ctx.lineTo(w, cy + 180);
                ctx.stroke();

                // Monolito Central 3D renderizado en slices ASCII
                const numFilas = 18;
                const sombraRamp = [' ', '░', '▒', '▓', '█'];
                ctx.font = 'bold 13px "Fira Code", monospace';
                ctx.textAlign = 'center';

                // Levitar suavemente
                const flotacionY = Math.sin(state.tiempo * 1.6) * 12;

                for (let i = 0; i < numFilas; i++) {
                    const t = (i / numFilas) - 0.5; // -0.5 a 0.5
                    const anchoFila = Math.floor(Math.cos(t * Math.PI * 0.6) * 16 + 8);
                    const yFila = cy - 110 + i * 14 + flotacionY;

                    // Calcular cara iluminada según ángulo de rotación
                    const luz1 = Math.cos(a + t * 2.0);
                    const luz2 = Math.sin(a + t * 2.0);
                    
                    let filaStr = '';
                    for (let c = -anchoFila; c <= anchoFila; c++) {
                        const u = c / anchoFila;
                        const factorLuz = Math.max(0, Math.min(1, (u * luz1 + luz2 * 0.5 + 1) * 0.5));
                        const charIdx = Math.floor(factorLuz * (sombraRamp.length - 1));
                        filaStr += sombraRamp[charIdx];
                    }

                    // Tono ámbar / dorado retro
                    const brilloFila = 0.5 + Math.sin(a + i * 0.3) * 0.3 + bass * 0.3;
                    ctx.fillStyle = `rgba(249, 226, 175, ${Math.min(1.0, brilloFila)})`;
                    ctx.shadowColor = '#d4af37';
                    ctx.shadowBlur = (i === Math.floor(numFilas / 2)) ? (12 + bass * 15) : 0;

                    ctx.fillText(`|${filaStr}|`, cx, yFila);
                }

                // Anillo Orbital 1 (Giro Horario)
                const radioX1 = 150;
                const radioY1 = 36;
                const ang1 = state.tiempo * 1.2;
                ctx.font = 'bold 11px "Fira Code", monospace';
                const runas1 = ['[▲]', '[◆]', '[●]', '[★]', '[✚]', '[✦]', '[■]'];
                for (let r = 0; r < runas1.length; r++) {
                    const theta = ang1 + (r * Math.PI * 2) / runas1.length;
                    const rx = cx + Math.cos(theta) * radioX1;
                    const ry = (cy + flotacionY) + Math.sin(theta) * radioY1;
                    const z = Math.sin(theta); // Profundidad

                    const alfaRuna = (z + 1.2) * 0.45;
                    ctx.fillStyle = `rgba(137, 180, 250, ${Math.min(1.0, alfaRuna)})`;
                    ctx.shadowColor = '#89b4fa';
                    ctx.shadowBlur = z > 0 ? 8 : 0;
                    ctx.fillText(runas1[r], rx, ry);
                }

                // Anillo Orbital 2 (Giro Antihorario Inclinado)
                const radioX2 = 120;
                const radioY2 = 28;
                const ang2 = -state.tiempo * 0.9;
                ctx.font = '10px "Fira Code", monospace';
                const runas2 = ['01', 'λ', 'Ω', '::', '{}', '=>', '10'];
                for (let r = 0; r < runas2.length; r++) {
                    const theta = ang2 + (r * Math.PI * 2) / runas2.length;
                    const rx = cx + Math.cos(theta) * radioX2;
                    const ry = (cy - 30 + flotacionY) + Math.sin(theta) * radioY2;
                    const z = Math.sin(theta);

                    const alfaRuna = (z + 1.2) * 0.4;
                    ctx.fillStyle = `rgba(203, 166, 247, ${Math.min(1.0, alfaRuna)})`;
                    ctx.shadowColor = '#cba6f7';
                    ctx.shadowBlur = z > 0 ? 6 : 0;
                    ctx.fillText(runas2[r], rx, ry);
                }

                ctx.restore();
            }
        });

        // -------------------------------------------------------------
        // 20. SANTUARIO TORII & PAGODA ZEN (ASCII Architecture & Sakura)
        // -------------------------------------------------------------
        this.registrarEfecto('ascii_santuario_torii', {
            nombre: 'Santuario Torii & Pagoda Zen',
            icono: 'fa-torii-gate',
            desc: 'Arquitectura tradicional japonesa en arte ASCII minimalista con caída suave de flores de cerezo.',
            init: (canvas, w, h, densidad) => {
                const petalos = [];
                const cantPetalos = Math.floor(35 * densidad);
                for (let i = 0; i < cantPetalos; i++) {
                    petalos.push({
                        x: Math.random() * w,
                        y: Math.random() * h,
                        vx: Math.random() * 25 + 15,
                        vy: Math.random() * 30 + 20,
                        char: ['*', '°', '·', '❀', '✿', '~'][Math.floor(Math.random() * 6)],
                        oscilacion: Math.random() * Math.PI * 2,
                        oscVel: Math.random() * 2 + 1,
                        alfa: Math.random() * 0.5 + 0.35
                    });
                }
                return { petalos, tiempo: 0 };
            },
            update: (dt, w, h, mouse, state, audio) => {
                state.tiempo += dt;
                const boostVel = (audio && audio.reactivo) ? audio.boostVelocidad : 1.0;

                for (let i = 0; i < state.petalos.length; i++) {
                    const p = state.petalos[i];
                    p.oscilacion += dt * p.oscVel;
                    p.x += (p.vx + Math.sin(p.oscilacion) * 15) * dt * boostVel;
                    p.y += (p.vy + Math.cos(p.oscilacion) * 8) * dt * boostVel;

                    if (mouse && mouse.activo) {
                        const dx = p.x - mouse.x;
                        const dy = p.y - mouse.y;
                        const dist = Math.hypot(dx, dy);
                        if (dist < 100 && dist > 1) {
                            p.x += (dx / dist) * 80 * dt;
                            p.y += (dy / dist) * 80 * dt;
                        }
                    }

                    if (p.x > w + 20) p.x = -20;
                    if (p.y > h + 20) {
                        p.y = -20;
                        p.x = Math.random() * w;
                    }
                }
            },
            render: (ctx, w, h, dt, mouse, state, time, audio) => {
                ctx.clearRect(0, 0, w, h);
                const cx = w * 0.5;
                const cy = h * 0.58;
                const bass = (audio && audio.reactivo) ? audio.energiaBass : 0;

                ctx.save();

                // 1. Luna Llena de Fondo en ASCII
                ctx.font = '10px "Fira Code", monospace';
                ctx.textAlign = 'center';
                const moonLines = [
                    '   .---.   ',
                    '  / ░░░ \\  ',
                    ' | ░░▒░░ | ',
                    '  \\ ░░░ /  ',
                    '   \'---\'   '
                ];
                ctx.fillStyle = 'rgba(255, 240, 200, 0.4)';
                ctx.shadowColor = '#f9e2af';
                ctx.shadowBlur = 10 + bass * 12;
                for (let m = 0; m < moonLines.length; m++) {
                    ctx.fillText(moonLines[m], cx + 160, cy - 170 + m * 12);
                }

                // 2. Nubes Dithered en ASCII
                ctx.shadowBlur = 0;
                ctx.font = '11px "Fira Code", monospace';
                ctx.fillStyle = 'rgba(166, 227, 161, 0.18)';
                const cloudOffset = (state.tiempo * 10) % (w + 200);
                ctx.fillText('  ░░▒▒▓▓▒▒░░        ░░▒▒░░  ', (cloudOffset - 100), cy - 130);
                ctx.fillText('░░▒▒▓▓██▓▓▒▒░░    ░░▒▒▓▓▒▒░░', (cloudOffset + 180) % (w + 200) - 100, cy - 90);

                // 3. Gran Torii Gate Central (Patrick Louis Venam Style)
                ctx.font = 'bold 12px "Fira Code", monospace';
                ctx.fillStyle = 'rgba(166, 227, 161, 0.85)';
                ctx.shadowColor = '#a6e3a1';
                ctx.shadowBlur = 6 + bass * 8;

                const torii = [
                    '  .==============================================.  ',
                    ' /================================================\\ ',
                    '\'------|------|----------------------|------|------\'',
                    '       |      |     [ ⛩ 禅 ZEN ]     |      |       ',
                    '       |      |                      |      |       ',
                    '   .===|======|======================|======|===.   ',
                    '   \'---|------|----------------------|------|---\'   ',
                    '       | ▓▓▓▓ |                      | ▓▓▓▓ |       ',
                    '       | ▓▓▓▓ |                      | ▓▓▓▓ |       ',
                    '       | ▓▓▓▓ |       .------.       | ▓▓▓▓ |       ',
                    '       | ▓▓▓▓ |      /  ░▒░   \\      | ▓▓▓▓ |       ',
                    '       | ▓▓▓▓ |     |  ( ☼ )  |      | ▓▓▓▓ |       ',
                    '       | ▓▓▓▓ |      \\  ░▒░   /      | ▓▓▓▓ |       ',
                    '       | ▓▓▓▓ |       \'--||--\'       | ▓▓▓▓ |       ',
                    '       | ▓▓▓▓ |          ||          | ▓▓▓▓ |       ',
                    '       | ▓▓▓▓ |                      | ▓▓▓▓ |       ',
                    '       | ▓▓▓▓ |                      | ▓▓▓▓ |       ',
                    '     /========\\                      /========\\     ',
                    '    /__________\\                    /__________\\    ',
                    '   [============]                  [============]   '
                ];

                for (let i = 0; i < torii.length; i++) {
                    ctx.fillText(torii[i], cx, cy - 100 + i * 14);
                }

                // 4. Suelo Dithered & Bambú Lateral
                ctx.font = '11px "Fira Code", monospace';
                ctx.fillStyle = 'rgba(148, 226, 213, 0.45)';
                ctx.shadowBlur = 0;
                ctx.fillText('░░▒▒▓▓██████████████████████████████████████████▓▓▒▒░░', cx, cy + 188);
                ctx.fillText('//////////////////////////////////////////////////////', cx, cy + 200);

                // 5. Pétalos de Sakura Flotantes
                ctx.font = '12px "Fira Code", monospace';
                for (let i = 0; i < state.petalos.length; i++) {
                    const p = state.petalos[i];
                    ctx.fillStyle = `rgba(243, 139, 168, ${p.alfa})`;
                    ctx.shadowColor = '#f38ba8';
                    ctx.shadowBlur = 4;
                    ctx.fillText(p.char, p.x, p.y);
                }

                ctx.restore();
            }
        });

        // -------------------------------------------------------------
        // 21. GUARDIÁN ONI CYBERPUNK (ASCII Mask & Data Runes)
        // -------------------------------------------------------------
        this.registrarEfecto('ascii_oni_cyberpunk', {
            nombre: 'Guardián Oni Cyberpunk',
            icono: 'fa-mask',
            desc: 'Máscara cibernética Oni en arte ASCII venam con visor de barrido óptico y corrientes de datos.',
            init: (canvas, w, h, densidad) => {
                const columnasData = [];
                const cantCols = 8;
                for (let i = 0; i < cantCols; i++) {
                    columnasData.push({
                        x: i < 4 ? 40 + i * 28 : w - 140 + (i - 4) * 28,
                        y: Math.random() * -h,
                        vel: Math.random() * 40 + 30,
                        items: ['0xFE', 'SYS', '░▒▓', 'ON1', 'HEX', '>>', '01', 'λ8', '[OK]']
                    });
                }
                return { tiempo: 0, columnasData, scanY: 0 };
            },
            update: (dt, w, h, mouse, state, audio) => {
                state.tiempo += dt;
                const boost = (audio && audio.reactivo) ? audio.boostVelocidad : 1.0;
                state.scanY = Math.sin(state.tiempo * 2.2) * 24;

                for (let i = 0; i < state.columnasData.length; i++) {
                    const c = state.columnasData[i];
                    c.y += c.vel * dt * boost;
                    if (c.y > h + 100) c.y = -60;
                }
            },
            render: (ctx, w, h, dt, mouse, state, time, audio) => {
                ctx.clearRect(0, 0, w, h);
                const cx = w * 0.5;
                const cy = h * 0.5;
                const bass = (audio && audio.reactivo) ? audio.energiaBass : 0;

                ctx.save();

                // 1. Columnas de Telemetría Lateral
                ctx.font = '10.5px "Fira Code", monospace';
                ctx.textAlign = 'left';
                for (let i = 0; i < state.columnasData.length; i++) {
                    const col = state.columnasData[i];
                    for (let j = 0; j < col.items.length; j++) {
                        const yItem = col.y + j * 16;
                        if (yItem < -20 || yItem > h + 20) continue;
                        const alfa = (1 - j / col.items.length) * 0.35;
                        ctx.fillStyle = `rgba(203, 166, 247, ${alfa})`;
                        ctx.fillText(col.items[j], col.x, yItem);
                    }
                }

                // 2. Máscara Oni Central en Arte ASCII
                ctx.textAlign = 'center';
                ctx.font = 'bold 12px "Fira Code", monospace';
                ctx.fillStyle = 'rgba(243, 139, 168, 0.85)';
                ctx.shadowColor = '#f38ba8';
                ctx.shadowBlur = 8 + bass * 12;

                // Parallax suave al cursor
                const offsetX = mouse && mouse.activo ? (mouse.x - cx) * 0.03 : 0;
                const offsetY = mouse && mouse.activo ? (mouse.y - cy) * 0.03 : 0;

                const oni = [
                    '               /\\                   /\\               ',
                    '              /  \\  ░░░░░░░░░░░░░  /  \\              ',
                    '             / /\\ \\/             \\/ /\\ \\             ',
                    '            / /  \\/   ▲       ▲   \\/  \\ \\            ',
                    '           / /    \\  / \\     / \\  /    \\ \\           ',
                    '          ( (      ) ) █)   (█ ( (      ) )          ',
                    '           \\ \\    / /             \\ \\    / /         ',
                    '            \\ \\  / /  .=========.  \\ \\  / /          ',
                    '             \\ \\/ /  /   ░░░░░   \\  \\ \\/ /           ',
                    '       .======\\  /==/  [ 0xON1 ]  \\==\\  /======.     ',
                    '      / ░░░░░░ \\/  |  ===========  |  \\/ ░░░░░░ \\    ',
                    '     |  ▓▓▓▓▓▓     |  |==[VIS]==|  |     ▓▓▓▓▓▓  |   ',
                    '      \\ ░░░░░░ /\\  |  ===========  |  /\\ ░░░░░░ /    ',
                    '       \'======/  \\==\\             /==/  \\======\'     ',
                    '             / /\\ \\  \\   ▓▓▓▓▓   /  / /\\ \\           ',
                    '            / /  \\ \\  \'=========\'  / /  \\ \\          ',
                    '           / /    \\ \\  | | | | |  / /    \\ \\         ',
                    '          ( (      ) ) \\_|_|_|_/ ( (      ) )        ',
                    '           \\_\\    /_/   \\▼▼▼▼▼/   \\_\\    /_/         ',
                    '              \\  /       \\___/       \\  /            ',
                    '               \\/                     \\/             '
                ];

                for (let i = 0; i < oni.length; i++) {
                    ctx.fillText(oni[i], cx + offsetX, cy - 130 + offsetY + i * 13);
                }

                // 3. Visor Láser de Escaneo Óptico
                ctx.fillStyle = '#00ffff';
                ctx.shadowColor = '#00ffff';
                ctx.shadowBlur = 14 + bass * 10;
                ctx.fillRect(cx - 50 + offsetX, cy - 2 + offsetY + state.scanY, 100, 2);

                ctx.restore();
            }
        });

        // -------------------------------------------------------------
        // 22. OLAS JAPONESAS & SOLSTICIO (Minimalist Dithered Wave)
        // -------------------------------------------------------------
        this.registrarEfecto('ascii_paisaje_zen', {
            nombre: 'Olas Japonesas & Solsticio',
            icono: 'fa-water',
            desc: 'Olas matemáticas dithered estilo Ukiyo-e en arte ASCII minimalista con gran sol naciente.',
            init: () => ({ tiempo: 0 }),
            update: (dt, w, h, mouse, state, audio) => {
                state.tiempo += dt;
            },
            render: (ctx, w, h, dt, mouse, state, time, audio) => {
                ctx.clearRect(0, 0, w, h);
                const cx = w * 0.5;
                const cy = h * 0.52;
                const bass = (audio && audio.reactivo) ? audio.energiaBass : 0;
                const t = state.tiempo;

                ctx.save();

                // 1. Gran Sol Naciente en ASCII
                ctx.font = 'bold 11px "Fira Code", monospace';
                ctx.textAlign = 'center';
                ctx.fillStyle = 'rgba(250, 179, 135, 0.45)';
                ctx.shadowColor = '#fab387';
                ctx.shadowBlur = 12 + bass * 16;

                const sol = [
                    '          .---.          ',
                    '       .-\' ░░░ \'-.       ',
                    '     .\'  ░░▒▒▒░░  \'.     ',
                    '    /  ░░▒▒▓▓▓▒▒░░  \\    ',
                    '   |  ░░▒▒▓▓█▓▓▒▒░░  |   ',
                    '   |  ░░▒▒▓▓█▓▓▒▒░░  |   ',
                    '    \\  ░░▒▒▓▓▓▒▒░░  /    ',
                    '     \'.  ░░▒▒▒░░  .\'     ',
                    '       \'-. ░░░ .-\'       ',
                    '          \'---\'          '
                ];
                for (let s = 0; s < sol.length; s++) {
                    ctx.fillText(sol[s], cx, cy - 140 + s * 13);
                }

                // 2. Grullas en Vuelo (Minimalist ASCII Birds)
                ctx.font = '11px "Fira Code", monospace';
                ctx.fillStyle = 'rgba(249, 226, 175, 0.6)';
                ctx.shadowBlur = 0;
                const birdX1 = ((t * 25) % (w + 100)) - 50;
                const birdX2 = (((t + 4) * 20) % (w + 100)) - 50;
                ctx.fillText('__/^\\__', birdX1, cy - 170 + Math.sin(t * 2) * 8);
                ctx.fillText(' __/\\__ ', birdX2, cy - 195 + Math.cos(t * 1.8) * 6);

                // 3. Tres Capas de Olas Dithered en Movimiento Paralaje
                const charRamp = [' ', '░', '▒', '▓', '█'];
                const pasoX = 14;
                const numCols = Math.floor(w / pasoX) + 2;

                const renderCapaOla = (yBase, amp, freq, vel, color, blur) => {
                    ctx.fillStyle = color;
                    ctx.shadowColor = color;
                    ctx.shadowBlur = blur;
                    ctx.textAlign = 'center';

                    for (let c = 0; c < numCols; c++) {
                        const x = c * pasoX;
                        const y = yBase + Math.sin(x * freq + t * vel) * amp + Math.cos(x * freq * 0.5 - t * vel * 0.4) * (amp * 0.5);
                        
                        // Generar cresta vertical
                        const hCresta = 4;
                        for (let k = 0; k < hCresta; k++) {
                            const ch = (k === 0) ? '^' : (k === 1 ? '░' : (k === 2 ? '▒' : '▓'));
                            ctx.fillText(ch, x, y + k * 12);
                        }
                    }
                };

                // Capa de fondo
                renderCapaOla(cy + 30, 16, 0.008, 1.2, 'rgba(137, 180, 250, 0.35)', 0);
                // Capa media
                renderCapaOla(cy + 75, 22, 0.012, -1.8, 'rgba(137, 220, 235, 0.55)', 4);
                // Capa frontal con espuma
                renderCapaOla(cy + 125, 28, 0.015, 2.2, 'rgba(166, 227, 161, 0.8)', 6 + bass * 6);

                ctx.restore();
            }
        });

        // -------------------------------------------------------------
        // 23. CAZA ESPACIAL INTERCEPTOR (ASCII Starship Cruiser)
        // -------------------------------------------------------------
        this.registrarEfecto('ascii_nave_interceptor', {
            nombre: 'Caza Espacial Interceptor',
            icono: 'fa-jet-fighter',
            desc: 'Nave espacial geométrica retro en arte ASCII venam cruzando el hiperespacio con estelas de plasma.',
            init: (canvas, w, h, densidad) => {
                const estrellas = [];
                const cant = Math.floor(65 * densidad);
                for (let i = 0; i < cant; i++) {
                    estrellas.push({
                        x: Math.random() * w,
                        y: Math.random() * h,
                        vel: Math.random() * 220 + 80,
                        char: ['·', '•', '+', 'x', '✦'][Math.floor(Math.random() * 5)],
                        alfa: Math.random() * 0.6 + 0.2
                    });
                }
                return { tiempo: 0, estrellas, naveX: w * 0.5, naveY: h * 0.52 };
            },
            update: (dt, w, h, mouse, state, audio) => {
                state.tiempo += dt;
                const boost = (audio && audio.reactivo) ? (1 + audio.energiaBass * 1.6) : 1.0;

                // Suave seguimiento del mouse
                if (mouse && mouse.activo) {
                    state.naveX += (mouse.x - state.naveX) * Math.min(1.0, dt * 3.5);
                    state.naveY += (mouse.y - state.naveY) * Math.min(1.0, dt * 3.5);
                } else {
                    state.naveX = w * 0.5 + Math.sin(state.tiempo * 1.2) * (w * 0.15);
                    state.naveY = h * 0.52 + Math.cos(state.tiempo * 0.9) * (h * 0.08);
                }

                // Desplazar campo estelar hacia la izquierda
                for (let i = 0; i < state.estrellas.length; i++) {
                    const e = state.estrellas[i];
                    e.x -= e.vel * dt * boost;
                    if (e.x < -20) {
                        e.x = w + 20;
                        e.y = Math.random() * h;
                    }
                }
            },
            render: (ctx, w, h, dt, mouse, state, time, audio) => {
                ctx.clearRect(0, 0, w, h);
                const bass = (audio && audio.reactivo) ? audio.energiaBass : 0;

                ctx.save();

                // 1. Campo Estelar en Parallax
                ctx.font = '12px "Fira Code", monospace';
                for (let i = 0; i < state.estrellas.length; i++) {
                    const e = state.estrellas[i];
                    ctx.fillStyle = `rgba(137, 180, 250, ${e.alfa})`;
                    ctx.fillText(e.char, e.x, e.y);
                }

                // 2. Nave Interceptor Central (Venam Isometric Fighter)
                const nx = state.naveX;
                const ny = state.naveY;

                ctx.font = 'bold 12px "Fira Code", monospace';
                ctx.textAlign = 'center';
                ctx.fillStyle = 'rgba(137, 220, 235, 0.9)';
                ctx.shadowColor = '#89dceb';
                ctx.shadowBlur = 8 + bass * 12;

                const ship = [
                    '                    /\\                    ',
                    '                   /  \\                   ',
                    '                  / /\\ \\                  ',
                    '                 / /  \\ \\                 ',
                    '                / /    \\ \\                ',
                    '               / /  /\\  \\ \\               ',
                    '  .===========/ /  /  \\  \\ \\===========.  ',
                    ' / ░░░░░░░░░░/ /  / /\\ \\  \\ \\░░░░░░░░░░ \\ ',
                    '|  ▓▓▓▓▓▓▓▓▓/ /  / /  \\ \\  \\ \\▓▓▓▓▓▓▓▓▓  |',
                    '|  [01-PRIG] /  / / == \\ \\  \\ [INTERCP]  |',
                    ' \\ ░░░░░░░░░/  / /  ||  \\ \\  \\░░░░░░░░░ / ',
                    '  \'========/  / /   ||   \\ \\  \\========\'  ',
                    '          /  / /    ||    \\ \\  \\          ',
                    '         /  / /     ||     \\ \\  \\         ',
                    '        /__/ /      ||      \\ \\__\\        ',
                    '       [====]      [==]      [====]       '
                ];

                for (let i = 0; i < ship.length; i++) {
                    ctx.fillText(ship[i], nx, ny - 100 + i * 13);
                }

                // 3. Estelas de Plasma Propulsor (Dithered Heat Trail)
                const thrusterLen = 6 + Math.floor(Math.random() * 4 + bass * 8);
                const plumas = ['█', '▓', '▒', '░', '·', ' '];
                ctx.font = '11px "Fira Code", monospace';
                ctx.fillStyle = '#00ffff';
                ctx.shadowColor = '#00ffff';
                ctx.shadowBlur = 14 + bass * 14;

                const tOffset1 = nx - 34;
                const tOffset2 = nx;
                const tOffset3 = nx + 34;
                const baseThrustY = ny + 110;

                for (let p = 0; p < thrusterLen; p++) {
                    const ch = plumas[Math.min(p, plumas.length - 1)];
                    const yP = baseThrustY + p * 12;
                    ctx.fillText(ch, tOffset1, yP);
                    ctx.fillText(ch, tOffset2, yP + 4);
                    ctx.fillText(ch, tOffset3, yP);
                }

                ctx.restore();
            }
        });

        // ====================================================================
        // TEMAS DINÁMICOS ASCII CON PAISAJES ESTRUCTURADOS EN LOS COSTADOS
        // ====================================================================

        // ====================================================================
        // TEMAS DINÁMICOS ASCII CON PAISAJES ESTRUCTURADOS EN LOS COSTADOS
        // ====================================================================

        const PAISAJES_LATERALES = {
            tema_mecha_patrol: {
                cielo: [
                    "✦ ·  °   .  [ORBITAL-DEFENSE-GRID • SECTOR-ALPHA-01]  .   °  · ✦",
                    "      ▲═══▲                    ▲═══▲                    ▲═══▲      ",
                    "    --[•]--                  --[•]--                  --[•]--    "
                ],
                izq: [
                    "╔══════[MECHA-BASTION-ALPHA]══════╗",
                    "║ █║ ░░░░░░░░░░░░░░░░░░░░░░░░ ║█ ║",
                    "║ █║ [CORE-REACTOR: 99.8%]   ║█ ║",
                    "║ █║ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ ║█ ║",
                    "╠══════╦════════════════╦══════╣",
                    "║ ///  ║ RADAR-ARRAY-01 ║  \\\\\\ ║",
                    "║ |||  ║ [SCAN: MONITOR]║  ||| ║",
                    "║ \\\\\\  ║ ░░░░░░░░░░░░░░ ║  /// ║",
                    "╠══════╩════════════════╩══════╣",
                    "║ █║ /// BARRACKS-SUB-LEVEL\\\\║█║",
                    "║ █║ █║█║█║█║█║█║█║█║█║█║█║█ ║█ ║",
                    "╠══════════════════════════════╣",
                    "║ ▓▓▓▓ [HEAVY-PLASMA-TURRET]   ║",
                    "║ █║======►►►► [CALIBER: 120]  ║",
                    "║ █║ ░░░░░░░░░░░░░░░░░░░░░░░ ║█ ║",
                    "╠══════╦════════════════╦══════╣",
                    "║ █║   ║ [AMMO-SILO-04] ║  ║█  ║",
                    "║ █║   ║ ▓▓▓▓ ▓▓▓▓ ▓▓▓▓ ║  ║█  ║",
                    "║ █║   ║ ░░░░ ░░░░ ░░░░ ║  ║█  ║",
                    "╠══════╩════════════════╩══════╣",
                    "║ [COOLANT-INJECTOR: NORMAL]   ║",
                    "║ █║ █║█║█║ ░░░░░░░ █║█║█║   ║█║",
                    "║ █║ ▓▓▓▓▓▓ ░░░░░░░ ▓▓▓▓▓▓   ║█║",
                    "╚══════════════════════════════╝"
                ],
                der: [
                    "╔══════[TOWER-BEACON-OMEGA]══════╗",
                    "║ █║ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ ║█ ║",
                    "║ █║ {Ω} QUANTUM-LINK: 100%  ║█ ║",
                    "║ █║ ░░░░░░░░░░░░░░░░░░░░░░░ ║█ ║",
                    "╠══════╦════════════════╦══════╣",
                    "║  ║   ║ [BATTERY-ARRAY]║   ║  ║",
                    "║  ║   ║ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓ ║   ║  ║",
                    "║  ║   ║ [PWR: 100% OK] ║   ║  ║",
                    "╠══╩═══╩════════════════╩═══╩══╣",
                    "║ █║ /// SHIELD-GEN-STAGE-2\\\\║█║",
                    "║ █║ ░░░░░░░░░░░░░░░░░░░░░░░ ║█ ║",
                    "║ █║ █║█║█║█║█║█║█║█║█║█║█║█ ║█ ║",
                    "╠══════════════════════════════╣",
                    "║ [DEFENSE-PERIMETER-STATION]  ║",
                    "║ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ ║",
                    "║ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ║",
                    "╠══════╦════════════════╦══════╣",
                    "║ █║   ║ [SUB-CARRIER]  ║  ║█  ║",
                    "║ █║   ║ ░░░░░ ▓▓▓▓▓    ║  ║█  ║",
                    "╚══════╩════════════════╩══════╝"
                ],
                horizonte: "══[BASE-GRID-01]═══════════════════════════════════════════════════════════════════════════[PERIMETER-SECURE]══"
            },
            tema_cyber_netrunner: {
                cielo: [
                    "010101  .---. [NEO-CYBERSPACE • 128-QUBIT FIBER-NET] .---.  101010",
                    "      // 01 \\\\                                      // 10 \\\\      ",
                    "     <[DATA-BUS]>                                  <[NODE-BUS]>    "
                ],
                izq: [
                    "┌───[NET-MEGATOWER-SECTOR-0]───┐",
                    "│ 0101 1100 0011 1010 0101 110 │",
                    "│ [ROOT-ACCESS: GRANTED-L4]    │",
                    "│ ░▒▓█ 128-QUBIT-HYPER-SOC █▓▒ │",
                    "├──────────────────────────────┤",
                    "│ > INJECT: PAYLOAD-STREAM [OK]│",
                    "│ > MEM-MAP: 0x7FFF_A800_C204  │",
                    "│ > CRYPTO-ROUTER: ENCRYPTED   │",
                    "│ ▓▓▓▓ ░░░░ ▒▒▒▒ █║█║█║█ ▓▓▓▓  │",
                    "├──────────────────────────────┤",
                    "│ > SYS-CORE: KERNEL-SECURE    │",
                    "│ 0110 1001 0101 1100 1101 001 │",
                    "│ █║█║█║█║█║█║█║█║█║█║█║█║█║█║ │",
                    "├──────────────────────────────┤",
                    "│ [NEURAL-FIBER-BUFFER-STACK]  │",
                    "│ ░░░░░░░░ ▓▓▓▓▓▓▓▓ █║█║█║ ▒▒▒ │",
                    "│ 1101 0010 1110 0101 0011 101 │",
                    "│ > PACKET-LOSS: 0.000%        │",
                    "│ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ │",
                    "└──────────────────────────────┘"
                ],
                der: [
                    "┌───[CORP-MAINFRAME-VAULT-X]───┐",
                    "│ █║█║█║█║█║█║█║█║█║█║█║█║█║█║ │",
                    "│ [QUANTUM-PROCESSOR-ARRAY-V]  │",
                    "│ {λ} HYPERCORE-PIPELINE: LIVE │",
                    "├──────────────────────────────┤",
                    "│ > PORT: 8080 [LISTENING-TCP] │",
                    "│ > LATENCY: 0.08ms ULTRA-FAST │",
                    "│ ░░░░ ▓▓▓▓ █║█║█ ▒▒▒▒▒▒ ░░░░  │",
                    "├──────────────────────────────┤",
                    "│ [CYBER-STACK-MONITOR-07]     │",
                    "│ 1101 0010 1110 0101 1100 010 │",
                    "│ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ │",
                    "├──────────────────────────────┤",
                    "│ [FIREWALL-GATE-ALPHA]        │",
                    "│ █║█ ░░░░ ▓▓▓▓ █║█ ░░░░ █║█   │",
                    "└──────────────────────────────┘"
                ],
                horizonte: "──[OPTICAL-FIBER-BUS]───────────────────────────────────────────────────────────────────────────[QUANTUM-LAYER]──"
            },
            tema_dragon_sanctuary: {
                cielo: [
                    "   (~~~-._   .---.   ZEN MIST & CELESTIAL DRAGON SHRINE   .---.   _.-~~~)   ",
                    "          '-(  ●  )-'                                   '-(  ●  )-'         ",
                    "            / | \\                                           / | \\           "
                ],
                izq: [
                    "           /\\           ",
                    "          /__\\          ",
                    "          |  |          ",
                    "        .------.        ",
                    "      //________\\\\      ",
                    "         | || |         ",
                    "       .--------.       ",
                    "     //__________\\\\     ",
                    "         | || |         ",
                    "       .--------.       ",
                    "     //__________\\\\     ",
                    "         | || |         ",
                    "      .------------.    ",
                    "    //______________\\\\  ",
                    "        | ||  || |      ",
                    "     .================. ",
                    "     |  ░░ ▓▓ ░░  ▓▓  | ",
                    "     |  ( ☯ ZEN ☯ )   | ",
                    "     [================] ",
                    "    ==================== "
                ],
                der: [
                    "           /\\           ",
                    "         .//\\\\.         ",
                    "        //______\\\\      ",
                    "          | || |        ",
                    "        .--------.      ",
                    "      //__________\\\\    ",
                    "          | || |        ",
                    "        .--------.      ",
                    "      //__________\\\\    ",
                    "          | || |        ",
                    "        .--------.      ",
                    "      //__________\\\\    ",
                    "        [========]      ",
                    "       ============     "
                ],
                horizonte: "~~*~~~~~*~~~~~~~~~*~~~~~~~~~~~~~~~~~~~[ SANCTUARIO ZEN DE LOS ARCES ]~~~~~~~~~~~~~~~~~~~~~~~~~*~~~~~~*~~~~~~"
            },
            tema_deep_space: {
                cielo: [
                    "✦  ·   °    ✦   [DEEP SPACE ODYSSEY • ANDROMEDA GATEWAY]   ✦    °   ·  ✦",
                    "     .---.                      ( ● )                      .---.     ",
                    "    / SAT \\                    [SOL-0]                    / SAT \\    "
                ],
                izq: [
                    "       .-----.       ",
                    "     .' ░░░░░ '.     ",
                    "    / ▓▓ [O] ▓▓ \\    ",
                    "   | █║ ( ● ) ║█ |   ",
                    "    \\ ▓▓ [=] ▓▓ /    ",
                    "     '. ░░░░░ .'     ",
                    "    ==◄◄ '---' ►►==  ",
                    "        / | \\        ",
                    "       |  |  |       ",
                    "      [=======]      ",
                    "     / ░░░░░░░ \\     ",
                    "    | ▓▓▓▓▓▓▓▓▓ |    ",
                    "    | █║█║█║█║█ |    ",
                    "     \\ ░░░░░░░ /     ",
                    "      [=======]      ",
                    "        / | \\        ",
                    "     /=========\\     ",
                    "    =============    "
                ],
                der: [
                    "         |         ",
                    "       --+--       ",
                    "         |         ",
                    "     .---|---.     ",
                    "     | ORBIT |     ",
                    "     | ░░░░░ |     ",
                    "     | ▓▓▓▓▓ |     ",
                    "     '-------'     ",
                    "       / | \\       ",
                    "      | █║█ |      ",
                    "       \\ | /       ",
                    "     '-------'     ",
                    "       |   |       ",
                    "      =======      "
                ],
                horizonte: "·······✦····················[ SECTOR GALÁCTICO 07 • VELOCIDAD WARP ]··························✦·············"
            },
            tema_dungeon_crawler: {
                cielo: [
                    "  † †   (  DARK CITADEL & ANCIENT RUNIC CATACOMBS  )   † †  ",
                    "      /\\  /\\                                         /\\  /\\      "
                ],
                izq: [
                    "      /\\     /\\      ",
                    "     /__\\   /__\\     ",
                    "     |  |   |  |     ",
                    "     |  |___|  |     ",
                    "     |  [░░░]  |     ",
                    "     |  [▓▓▓]  |     ",
                    "     |  [███]  |     ",
                    "    .--------------. ",
                    "    |  (†)  (†)    | ",
                    "    |  [GARGOYLE]  | ",
                    "    |  [░░░ ▓▓▓]   | ",
                    "    '--------------' ",
                    "     |  ||   ||  |   ",
                    "     |  ||   ||  |   ",
                    "     |  [░░░░░]  |   ",
                    "     |  [▓▓▓▓▓]  |   ",
                    "    [=============]  ",
                    "   ================= "
                ],
                der: [
                    "        /\\        ",
                    "       /__\\       ",
                    "       |  |       ",
                    "      .----.      ",
                    "      |(†) |      ",
                    "      |RUNA|      ",
                    "      |    |      ",
                    "      .----.      ",
                    "      | █║ |      ",
                    "      | ▓▓ |      ",
                    "      |    |      ",
                    "      [====]      ",
                    "       |  |       ",
                    "     ========     "
                ],
                horizonte: "††††††††††††††††††††††††††††[ CATACUMBA ANCESTRAL DE LAS RUNAS ]†††††††††††††††††††††††††††††††††††††††††††"
            },
            tema_wild_nature: {
                cielo: [
                    "  ▲▲▲  (~~~  MYSTIC ENCHANTED FOREST & MOUNTAINS  ~~~)  ▲▲▲  ",
                    "        /\\                                             /\\        "
                ],
                izq: [
                    "       /\\       ",
                    "      /  \\      ",
                    "     / /\\ \\     ",
                    "      /  \\      ",
                    "     / /\\ \\     ",
                    "    / /  \\ \\    ",
                    "      /  \\      ",
                    "     / /\\ \\     ",
                    "    / /  \\ \\    ",
                    "   / / /\\ \\ \\   ",
                    "      /  \\      ",
                    "     / /\\ \\     ",
                    "    / /  \\ \\    ",
                    "   / / /\\ \\ \\   ",
                    "       ||       ",
                    "       ||       ",
                    "      ====      "
                ],
                der: [
                    "       /\\       ",
                    "      //\\\\      ",
                    "     ///\\\\\\     ",
                    "      //\\\\      ",
                    "     ///\\\\\\     ",
                    "    ////\\\\\\\\    ",
                    "      //\\\\      ",
                    "     ///\\\\\\     ",
                    "    ////\\\\\\\\    ",
                    "       ||       ",
                    "       ||       ",
                    "      ====      "
                ],
                horizonte: "▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲[ BOSQUE MÍSTICO • CORRIENTE DE VIDA ]▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲"
            },
            tema_retro_arcade: {
                cielo: [
                    "★ ★  ╔═[ 8-BIT RETRO ARCADE CHAMPIONSHIP • 1989 ]═╗  ★ ★",
                    "     ║  HIGH-SCORE: 999990     STAGE-MAX: 99    ║      "
                ],
                izq: [
                    "╔═════[CABINET-01]═════╗",
                    "║  1-UP       2-UP     ║",
                    "║  99990      88420    ║",
                    "║ ★ ★ ★      ★ ★ ★     ║",
                    "╠══════════════════════╣",
                    "║    [PAC-MAN-PRO]     ║",
                    "║        (• •)         ║",
                    "║        \\___/         ║",
                    "╠══════════════════════╣",
                    "║  [JOYSTICK-ACTIVE]   ║",
                    "║        (O)           ║",
                    "║         |            ║",
                    "╠══════════════════════╣",
                    "║  [INSERT-COIN-1]     ║",
                    "║  [CREDITS: 04]       ║",
                    "╚══════════════════════╝"
                ],
                der: [
                    "╔═════[CABINET-02]═════╗",
                    "║   [SPACE-INVADERS]   ║",
                    "║    888880  HI-SCR    ║",
                    "╠══════════════════════╣",
                    "║       ▲  ▲  ▲        ║",
                    "║       ■  ■  ■        ║",
                    "║       ●  ●  ●        ║",
                    "╠══════════════════════╣",
                    "║   [READY-PLAYER-1]   ║",
                    "║   [PUSH-START-BTN]   ║",
                    "╚══════════════════════╝"
                ],
                horizonte: "■■■■■■■■■■■■■■■■■■■■■■■■■■■■[ RETRO 8-BIT ARCADE ZONE • 1989 ]■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■"
            },
            tema_quantum_void: {
                cielo: [
                    "λ Ω  [4D HYPERDIMENSIONAL TESSERACT & DIRAC TENSORS]  Ω λ",
                    "      /\\ /\\                                           /\\ /\\      "
                ],
                izq: [
                    "      /\\ /\\      ",
                    "     /  X  \\     ",
                    "    / /░░░\\ \\    ",
                    "    \\ \\▓▓▓/ /    ",
                    "     \\  X  /     ",
                    "      \\/ \\/      ",
                    "      /\\ /\\      ",
                    "     /  █  \\     ",
                    "    / / λ \\ \\    ",
                    "    \\ \\ ░ / /    ",
                    "     \\  ▓  /     ",
                    "      \\/ \\/      ",
                    "      /\\ /\\      ",
                    "     /  Ω  \\     ",
                    "    / / █ \\ \\    ",
                    "    \\_______/    "
                ],
                der: [
                    "       /\\       ",
                    "      /  \\      ",
                    "     / 4D \\     ",
                    "     \\ ░░ /     ",
                    "      \\  /      ",
                    "       \\/       ",
                    "       /\\       ",
                    "      / Ω \\     ",
                    "     /  █  \\    ",
                    "     \\ ░░ /     ",
                    "      \\  /      ",
                    "       \\/       ",
                    "     /______\\   "
                ],
                horizonte: "⠁⠃⠇⠏⠟⠿░▒▓█[ TENSORES HIPERDIMENSIONALES • ESPACIO CUÁNTICO EN 4D ]█▓▒░⠿⠟⠏⠇⠃⠁⠁⠃⠇⠏⠟⠿░▒▓█"
            },
            tema_neural_cybergrid: {
                cielo: [
                    "0101  ⚡  [NEURAL DATA HIGHWAY • SYNAPSE MATRIX 2088]  ⚡  1010",
                    "      <==[NODE-ALPHA]==>                      <==[NODE-OMEGA]==>      "
                ],
                izq: [
                    "╔════[SYNAPSE-DATA-ROUTER]════╗",
                    "║ █║ 0101 1100 0011 1010 ║█ ║",
                    "║ █║ [THROUGHPUT: 120 TB/s] ║█ ║",
                    "║ █║ ░▒▓█ OPTICAL-FIBER █▓▒ ║█ ║",
                    "╠════╦════════════════════╦════╣",
                    "║ >> ║ LATENCY: 0.04ms    ║ << ║",
                    "║ >> ║ [ASYNC-COROUTINES] ║ << ║",
                    "╠════╩════════════════════╩════╣",
                    "║ [NEURAL-CORE-PROCESSOR-X]   ║",
                    "║ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ ║",
                    "║ █║█║█║█║█║█║█║█║█║█║█║█║█║█║ ║",
                    "╠══════════════════════════════╣",
                    "║ > MEM-BUFFER: ZERO-COPY      ║",
                    "║ > PACKET-LOSS: 0.000%        ║",
                    "╚══════════════════════════════╝"
                ],
                der: [
                    "╔════[HYPER-SERVER-STATION]═══╗",
                    "║ █║█║█║█║█║█║█║█║█║█║█║█║█║█║ ║",
                    "║ [MICROSERVICE-MESH: OK]     ║",
                    "╠══════════════════════════════╣",
                    "║ 0110 1001 0101 1100 1101 001 ║",
                    "║ ░░░░ ▓▓▓▓ █║█║█ ▒▒▒▒ ░░░░    ║",
                    "╠══════════════════════════════╣",
                    "║ [DISTRIBUTED-CACHE-CLUSTER]  ║",
                    "║ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ ║",
                    "╚══════════════════════════════╝"
                ],
                horizonte: "══[FIBER-OPTIC-HIGHWAY]═══════════════════════════════════════════════════════════════════════════[SYNAPSE-SECURE]══"
            },
            tema_steampunk_observatory: {
                cielo: [
                    "⚙ ☼  ( VICTORIAN CELESTIAL CLOCKWORK OBSERVATORY )  ☼ ⚙",
                    "      /===\\                                          /===\\      "
                ],
                izq: [
                    "        .-------.        ",
                    "      .'  ( ☼ )  '.      ",
                    "     /  ░░ ▓▓ ░░   \\     ",
                    "    | [ASTROLABE]   |    ",
                    "     \\  ░░ ▓▓ ░░   /     ",
                    "      '.  ( ⚙ )  .'      ",
                    "     ---'=======`---     ",
                    "        / | | | \\        ",
                    "       |  █ █ █  |       ",
                    "      [===========]      ",
                    "     /  BRASS-GEAR \\     ",
                    "    |  (o) (o) (o)  |    ",
                    "    | ▓▓▓▓▓▓▓▓▓▓▓▓▓ |    ",
                    "     \\  ░░░░░░░░░  /     ",
                    "      [===========]      ",
                    "        / | | | \\        ",
                    "       =============     "
                ],
                der: [
                    "         |===|         ",
                    "        ( ⚙-⚙ )        ",
                    "      .---|-|---.      ",
                    "      | CLOCK-V |      ",
                    "      | ░░░ ▓▓▓ |      ",
                    "      '---------'      ",
                    "        / | | \\        ",
                    "       | █║ ║█ |       ",
                    "      '---------'      ",
                    "        / | | \\        ",
                    "       =========       "
                ],
                horizonte: "⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙[ OBSERVATORIO VICTORIANO DE ENGRANAJES ]⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙⚙"
            },
            tema_bioluminescent_abyss: {
                cielo: [
                    "≈ ≈  ~  ( DEEP SEA BIOLUMINESCENT TRENCH & HYDROTHERMAL VENTS )  ~  ≈ ≈",
                    "      ( o )                                          ( o )      "
                ],
                izq: [
                    "          .-''''-.          ",
                    "        .'  o  o  '.        ",
                    "       /  ( ░░░ )   \\       ",
                    "      |  BIOLUM-JELLY|      ",
                    "       \\  ▓▓▓▓▓▓▓▓  /       ",
                    "        '.        .'        ",
                    "       / / / \\ \\ \\ \\        ",
                    "      ( ( (   ) ) ) )       ",
                    "       \\ \\ \\ / / / /        ",
                    "      ( ( (   ) ) ) )       ",
                    "       \\ \\ \\ / / / /        ",
                    "        ||||||||||||        ",
                    "     .================.     ",
                    "     | CORAL-CATHEDRAL|     ",
                    "     | ░░ ▓▓ ░░ ▓▓ ░░ |     ",
                    "    ====================    "
                ],
                der: [
                    "         .-''''-.         ",
                    "       .'  ~  ~  '.       ",
                    "      /   [ABYSS]  \\      ",
                    "     |  ░░ ▓▓ ░░ ▓▓ |     ",
                    "      \\  ( ∘ ∘ )   /      ",
                    "       '.        .'       ",
                    "        / / \\ \\ \\         ",
                    "       ( (   ) ) )        ",
                    "        \\ \\ / / /         ",
                    "       ==========         "
                ],
                horizonte: "~~~~~~~~~~~~~~~~~~~~~~~~~~~~[ FOSA MARINA ABISAL • CORRIENTES LUMINISCENTES ]~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~"
            },
            tema_alchemist_laboratory: {
                cielo: [
                    "✧ 🜂  ⚗  [ ARCANUM ALCHEMICAL LABORATORY & TRANSMUTATION CIRCLE ]  ⚗  🜂 ✧",
                    "      /\\  /\\                                          /\\  /\\      "
                ],
                izq: [
                    "         .-----.         ",
                    "        /  ⚗-⚗  \\        ",
                    "       | ALEMBIQUE|      ",
                    "       | ░░ ▓▓ ░░ |      ",
                    "        \\  (🜂)   /       ",
                    "      ---'====='---      ",
                    "         |  |  |         ",
                    "      .------------.     ",
                    "      | TRANSMUTAR |     ",
                    "      | ░░░ ▓▓▓ █║ |     ",
                    "      | [RUNA-GOLD]|     ",
                    "      '------------'     ",
                    "       /  ||  ||  \\      ",
                    "      [============]     ",
                    "     /  CRISTAL-ARC \\    ",
                    "    | ▓▓▓▓▓▓▓▓▓▓▓▓▓▓ |   ",
                    "    ==================   "
                ],
                der: [
                    "         .----.         ",
                    "        /  🜁  \\        ",
                    "       | HERMET |       ",
                    "       | ░░  ▓▓ |       ",
                    "        \\  (✧) /        ",
                    "        '------'        ",
                    "         / || \\         ",
                    "       .--------.       ",
                    "       | RUNA-X |       ",
                    "       '--------'       ",
                    "        /  ||  \\        ",
                    "       ==========       "
                ],
                horizonte: "✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧[ LABORATORIO ALQUÍMICO DE TRANSMUTACIÓN ]✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧✧"
            }
        };

        const registrarTemaDirectorLLM = (temaId, configTema) => {
            this.registrarEfecto(temaId, {
                init: (canvas, w, h) => {
                    const width = (typeof w === 'number' && w > 0) ? w : (canvas && canvas.width ? canvas.width : window.innerWidth);
                    const height = (typeof h === 'number' && h > 0) ? h : (canvas && canvas.height ? canvas.height : window.innerHeight);
                    if (window.DIRECTOR_ASCII) {
                        window.DIRECTOR_ASCII.inicializarEscenario(temaId);
                    }

                    // Generar partículas concentradas en los costados periféricos
                    const particulas = [];
                    const count = configTema.particulasCount || 32;
                    for (let i = 0; i < count; i++) {
                        const enCostados = Math.random() < 0.88;
                        let posX;
                        if (enCostados) {
                            posX = Math.random() < 0.5 ? Math.random() * (width * 0.16) : width * 0.84 + Math.random() * (width * 0.16);
                        } else {
                            posX = width * 0.18 + Math.random() * (width * 0.64);
                        }

                        particulas.push({
                            x: posX,
                            y: Math.random() * height,
                            velX: (Math.random() - 0.5) * (configTema.velX || 15),
                            velY: (Math.random() * 0.8 + 0.2) * (configTema.velY || 25),
                            char: configTema.simbolos[Math.floor(Math.random() * configTema.simbolos.length)],
                            alfa: enCostados ? (Math.random() * 0.28 + 0.12) : (Math.random() * 0.06 + 0.02),
                            tam: 9 + Math.random() * 2.5
                        });
                    }
                    return { tiempo: 0, particulas };
                },
                update: (dt, w, h, mouse, state, audio) => {
                    state.tiempo += dt;
                    const boost = (audio && audio.reactivo) ? (1 + audio.energiaBass * 1.5) : 1.0;

                    for (let i = 0; i < state.particulas.length; i++) {
                        const p = state.particulas[i];
                        p.x += p.velX * dt * boost;
                        p.y += p.velY * dt * boost;

                        if (p.y > h + 20) { p.y = -20; }
                        if (p.x < -20) p.x = w * 0.15;
                        if (p.x > w + 20) p.x = w * 0.85;
                    }

                    if (window.DIRECTOR_ASCII) {
                        window.DIRECTOR_ASCII.actualizar(dt, this.cursorTexto, w, h);
                    }
                },
                render: (ctx, w, h, dt, mouse, state, time, audio) => {
                    ctx.clearRect(0, 0, w, h);
                    const bass = (audio && audio.reactivo) ? audio.energiaBass : 0;
                    const tRel = (time || performance.now()) * 0.001;

                    ctx.save();

                    // 1. MÁSCARA CENTRAL DE ALTO CONTRASTE (Zona del Editor Monaco con visibilidad cristalina)
                    const gradCentro = ctx.createLinearGradient(0, 0, w, 0);
                    gradCentro.addColorStop(0, 'rgba(6, 9, 17, 0.10)');
                    gradCentro.addColorStop(0.18, 'rgba(6, 9, 17, 0.55)');
                    gradCentro.addColorStop(0.50, 'rgba(6, 9, 17, 0.65)');
                    gradCentro.addColorStop(0.82, 'rgba(6, 9, 17, 0.55)');
                    gradCentro.addColorStop(1, 'rgba(6, 9, 17, 0.10)');
                    ctx.fillStyle = gradCentro;
                    ctx.fillRect(0, 0, w, h);

                    // 2. RENDERIZAR PAISAJES EN PERSPECTIVA PROFUNDA (Alejados en el fondo con micro-escala)
                    const paisaje = PAISAJES_LATERALES[temaId];
                    if (paisaje) {
                        // Cielo lejano en movimiento de deriva horizontal suave
                        if (paisaje.cielo) {
                            ctx.font = '6.5px "Fira Code", monospace';
                            ctx.textAlign = 'center';
                            const alfaCielo = 0.14 + Math.sin(tRel * 0.8) * 0.04 + bass * 0.08;
                            ctx.fillStyle = configTema.colorParticulas.replace('__A__', Math.min(0.35, Math.max(0.06, alfaCielo)).toFixed(2));

                            const shiftCielo = Math.sin(tRel * 0.35) * 14;
                            for (let s = 0; s < paisaje.cielo.length; s++) {
                                ctx.fillText(paisaje.cielo[s], w * 0.5 + shiftCielo * (s % 2 === 0 ? 1 : -0.7), 12 + s * 9.5);
                            }
                        }

                        // Columna lateral izquierda (arquitectura en perspectiva lejana: 6.2px)
                        ctx.font = '6.2px "Fira Code", monospace';
                        if (paisaje.izq) {
                            ctx.textAlign = 'left';
                            const inicioYIzq = Math.max(25, h * 0.06);
                            for (let j = 0; j < paisaje.izq.length; j++) {
                                const pulsoFila = 0.18 + Math.sin(tRel * 2.0 + j * 0.25) * 0.05 + bass * 0.10;
                                const swayX = Math.sin(tRel * 0.5 + j * 0.12) * 1.2;
                                const swayY = Math.cos(tRel * 0.8 + j * 0.18) * 0.8;
                                ctx.fillStyle = configTema.colorParticulas.replace('__A__', Math.min(0.40, Math.max(0.06, pulsoFila)).toFixed(2));
                                ctx.fillText(paisaje.izq[j], 6 + swayX, inicioYIzq + j * 8.2 + swayY);
                            }
                        }

                        // Columna lateral derecha (perspectiva lejana: 6.2px)
                        if (paisaje.der) {
                            ctx.textAlign = 'right';
                            const inicioYDer = Math.max(25, h * 0.06);
                            for (let k = 0; k < paisaje.der.length; k++) {
                                const pulsoDer = 0.18 + Math.cos(tRel * 2.0 + k * 0.25) * 0.05 + bass * 0.10;
                                const swayDerX = Math.cos(tRel * 0.5 + k * 0.12) * 1.2;
                                const swayDerY = Math.sin(tRel * 0.8 + k * 0.18) * 0.8;
                                ctx.fillStyle = configTema.colorParticulas.replace('__A__', Math.min(0.40, Math.max(0.06, pulsoDer)).toFixed(2));
                                ctx.fillText(paisaje.der[k], w - 6 + swayDerX, inicioYDer + k * 8.2 + swayDerY);
                            }
                        }

                        // Línea de horizonte inferior lejana con flujo de escaneo continuo
                        if (paisaje.horizonte) {
                            ctx.textAlign = 'center';
                            const alfaHoriz = 0.15 + Math.sin(tRel * 1.6) * 0.04 + bass * 0.08;
                            const shiftHoriz = Math.sin(tRel * 0.4) * 8;
                            ctx.fillStyle = configTema.colorParticulas.replace('__A__', Math.min(0.35, Math.max(0.05, alfaHoriz)).toFixed(2));
                            ctx.fillText(paisaje.horizonte, w * 0.5 + shiftHoriz, h - 6);
                        }
                    }

                    // 3. Partículas sutiles en la lejanía periférica
                    ctx.font = '7.5px "Fira Code", monospace';
                    ctx.textAlign = 'center';
                    for (let i = 0; i < state.particulas.length; i++) {
                        const p = state.particulas[i];
                        ctx.fillStyle = configTema.colorParticulas.replace('__A__', (p.alfa * 0.65 + bass * 0.08).toFixed(2));
                        ctx.fillText(p.char, p.x, p.y);
                    }

                    // 4. Renderizar cuadro de diálogo fijo ampliado y personaje en la zona inferior derecha
                    if (window.DIRECTOR_ASCII) {
                        window.DIRECTOR_ASCII.dibujar(ctx, w, h);
                    }

                    ctx.restore();
                }
            });
        };

        // 1. Mecha Titan Defense
        registrarTemaDirectorLLM('tema_mecha_patrol', {
            simbolos: ['·', '░', '▓', '▲', '⚡', '►'],
            colorParticulas: 'rgba(166, 227, 161, __A__)',
            particulasCount: 30,
            velY: 20,
            velX: 10
        });

        // 2. Netrunner 2077
        registrarTemaDirectorLLM('tema_cyber_netrunner', {
            simbolos: ['0', '1', 'λ', 'Ω', '░', '▒', '▓'],
            colorParticulas: 'rgba(243, 139, 168, __A__)',
            particulasCount: 35,
            velY: 35,
            velX: 0
        });

        // 3. Santuario del Dragón
        registrarTemaDirectorLLM('tema_dragon_sanctuary', {
            simbolos: ['*', '🌸', '·', '°', '░', '✧'],
            colorParticulas: 'rgba(245, 194, 231, __A__)',
            particulasCount: 25,
            velY: 15,
            velX: 15
        });

        // 4. Odisea Interestelar
        registrarTemaDirectorLLM('tema_deep_space', {
            simbolos: ['·', '•', '+', '✦', '✧', '°'],
            colorParticulas: 'rgba(137, 180, 250, __A__)',
            particulasCount: 30,
            velY: -12,
            velX: -8
        });

        // 5. Catacumba Rúnica
        registrarTemaDirectorLLM('tema_dungeon_crawler', {
            simbolos: ['░', '▒', '†', '‡', '§', '¶'],
            colorParticulas: 'rgba(203, 166, 247, __A__)',
            particulasCount: 25,
            velY: -18,
            velX: 8
        });

        // 6. Bosque Místico
        registrarTemaDirectorLLM('tema_wild_nature', {
            simbolos: ['·', '˚', '°', '🍃', '░', '✦'],
            colorParticulas: 'rgba(148, 226, 213, __A__)',
            particulasCount: 25,
            velY: 12,
            velX: 20
        });

        // 7. Arcade 1989
        registrarTemaDirectorLLM('tema_retro_arcade', {
            simbolos: ['■', '▲', '▼', '★', '♦', '●'],
            colorParticulas: 'rgba(249, 226, 175, __A__)',
            particulasCount: 30,
            velY: 30,
            velX: 0
        });

        // 8. Vacío Isométrico
        registrarTemaDirectorLLM('tema_quantum_void', {
            simbolos: ['⠁', '⠃', '⠇', '⠏', '⠟', '⠿', '░', '▒'],
            colorParticulas: 'rgba(186, 194, 222, __A__)',
            particulasCount: 25,
            velY: 15,
            velX: 15
        });

        // 9. Autopista Cybergrid Neuronal
        registrarTemaDirectorLLM('tema_neural_cybergrid', {
            simbolos: ['1', '0', '╢', '╟', '█', '░', '⚡'],
            colorParticulas: 'rgba(137, 220, 235, __A__)',
            particulasCount: 35,
            velY: 38,
            velX: 0
        });

        // 10. Observatorio Steampunk
        registrarTemaDirectorLLM('tema_steampunk_observatory', {
            simbolos: ['⚙', '✦', '·', '░', '▓', '☼'],
            colorParticulas: 'rgba(249, 226, 175, __A__)',
            particulasCount: 28,
            velY: 14,
            velX: 14
        });

        // 11. Abismo Bioluminiscente
        registrarTemaDirectorLLM('tema_bioluminescent_abyss', {
            simbolos: ['~', '≈', '∘', '°', '░', '✦'],
            colorParticulas: 'rgba(116, 199, 236, __A__)',
            particulasCount: 28,
            velY: -16,
            velX: 10
        });

        // 12. Laboratorio del Alquimista
        registrarTemaDirectorLLM('tema_alchemist_laboratory', {
            simbolos: ['⚗', '☿', '🜂', '░', '▓', '✧'],
            colorParticulas: 'rgba(203, 166, 247, __A__)',
            particulasCount: 28,
            velY: 18,
            velX: -10
        });
    }
}

// Instanciar motor global
window.MotorMovimientoFondo = MotorMovimientoFondo;
window.motorMovimiento = new MotorMovimientoFondo();


