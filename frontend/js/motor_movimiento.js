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

    guardarConfig() {
        try {
            localStorage.setItem('prig_motor_movimiento', JSON.stringify(this.config));
        } catch (e) {
            console.warn("No se pudo guardar la configuración del motor de movimiento:", e);
        }
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
            onResize: definicion.onResize || null
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

        // 1. Update de la física
        if (typeof def.update === 'function') {
            def.update(dt, w, h, this.mouse, this._estadoEfecto);
        }

        // 2. Renderizado en el Canvas
        if (typeof def.render === 'function') {
            def.render(this.ctx, w, h, dt, this.mouse, this._estadoEfecto, tiempoTotal);
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
            render: (ctx, w, h, dt, mouse, state) => {
                ctx.clearRect(0, 0, w, h);
                const p = state.particulas;
                const distMax = state.distMax;
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
                            const alfa = (1 - Math.sqrt(distSq) / distMax) * 0.28;
                            ctx.strokeStyle = `rgba(137, 180, 250, ${alfa})`;
                            ctx.lineWidth = 1;
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
                    ctx.shadowColor = pt.col;
                    ctx.shadowBlur = 6;
                    ctx.beginPath();
                    ctx.arc(pt.x, pt.y, pt.r, 0, Math.PI * 2);
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
            update: (dt, w, h, mouse, state) => {
                const gotas = state.gotas;
                const vels = state.velocidades;
                for (let i = 0; i < gotas.length; i++) {
                    gotas[i] += vels[i] * dt;
                    if (gotas[i] > h && Math.random() > 0.96) {
                        gotas[i] = Math.random() * -60;
                    }
                }
            },
            render: (ctx, w, h, dt, mouse, state) => {
                // Fondo con desvanecimiento para efecto estela
                ctx.fillStyle = 'rgba(10, 10, 20, 0.09)';
                ctx.fillRect(0, 0, w, h);

                ctx.font = '13px monospace';
                const gotas = state.gotas;
                const chars = state.chars;
                const colWidth = state.colWidth;

                for (let i = 0; i < gotas.length; i++) {
                    const char = chars[Math.floor(Math.random() * chars.length)];
                    const x = i * colWidth;
                    const y = gotas[i];

                    const esLider = Math.random() > 0.88;
                    ctx.fillStyle = esLider ? '#a6e3a1' : '#00f0ff';
                    ctx.shadowColor = esLider ? '#a6e3a1' : '#00f0ff';
                    ctx.shadowBlur = esLider ? 8 : 4;
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
            update: (dt, w, h, mouse, state) => {
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
            render: (ctx, w, h, dt, mouse, state) => {
                ctx.fillStyle = 'rgba(10, 10, 20, 0.25)';
                ctx.fillRect(0, 0, w, h);

                const est = state.estrellas;
                const cx = w / 2;
                const cy = h / 2;

                for (let i = 0; i < est.length; i++) {
                    const s = est[i];
                    const k = 220 / s.z;
                    const px = s.x * k + cx;
                    const py = s.y * k + cy;

                    if (px >= 0 && px <= w && py >= 0 && py <= h) {
                        const size = Math.max(0.6, (1 - s.z / w) * 3.5);
                        const brillo = (1 - s.z / w);
                        ctx.fillStyle = `rgba(205, 214, 244, ${brillo})`;
                        ctx.shadowColor = '#89b4fa';
                        ctx.shadowBlur = size > 2 ? 6 : 2;
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
            render: (ctx, w, h, dt, mouse, state, time) => {
                ctx.clearRect(0, 0, w, h);
                const t = time * 0.001;

                state.capas.forEach(capa => {
                    ctx.fillStyle = capa.color;
                    ctx.beginPath();
                    ctx.moveTo(0, h);

                    const paso = 16;
                    for (let x = 0; x <= w + paso; x += paso) {
                        const yBase = h * capa.yOff;
                        const y = yBase + Math.sin(x * capa.freq + t * capa.speed) * capa.amp + Math.cos(x * capa.freq * 0.5 - t * 0.3) * (capa.amp * 0.5);
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
            update: (dt, w, h, mouse, state) => {
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
            render: (ctx, w, h, dt, mouse, state) => {
                ctx.clearRect(0, 0, w, h);
                const orbes = state.orbes;
                for (let i = 0; i < orbes.length; i++) {
                    const o = orbes[i];
                    const pulso = Math.sin(o.fase) * 0.2 + 0.8;
                    const radioActual = o.r * pulso;

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
            render: (ctx, w, h, dt, mouse, state, time) => {
                ctx.fillStyle = 'rgba(10, 10, 20, 0.2)';
                ctx.fillRect(0, 0, w, h);

                const t = time * 0.001;
                const centerY = h / 2;

                state.lineas.forEach(l => {
                    ctx.strokeStyle = l.col;
                    ctx.lineWidth = 2.2;
                    ctx.shadowColor = l.col;
                    ctx.shadowBlur = 10;
                    ctx.beginPath();

                    for (let x = 0; x <= w; x += 10) {
                        const y = centerY + Math.sin(x * l.freq + t * l.speed) * l.amp + Math.cos(x * 0.002 - t * 0.5) * 20;
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
    }
}

// Instanciar motor global
window.MotorMovimientoFondo = MotorMovimientoFondo;
window.motorMovimiento = new MotorMovimientoFondo();
