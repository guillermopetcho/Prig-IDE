/**
 * ==============================================================================
 * motor_grafico_fachada.js — Fachada Gráfica Dual (Rust WASM + Fallback JS)
 * ==============================================================================
 * Gestiona la conmutación transparente entre el motor matemático de alto rendimiento
 * en Rust WebAssembly (prig-render-wasm) y el motor JavaScript clásico.
 * 
 * Regla de Oro: Cero Regresiones.
 * Arquitectura de 3 niveles de resiliencia:
 *   1. Nivel 1 (Máximo Rendimiento): Web Worker con OffscreenCanvas + Rust WASM.
 *      El hilo principal y Monaco Editor quedan libres al 100% de cómputo gráfico.
 *   2. Nivel 2 (Fallback WASM en Hilo Principal): Rust WASM con lectura Zero-Copy.
 *   3. Nivel 3 (Fallback JS Clásico): Motor JavaScript Canvas 2D sin interrupciones.
 * 
 * Audio Reactivo: Purificado y eliminado al 100%. Bucle de renderizado determinista.
 */

class MotorGraficoFachada {
    constructor() {
        this.modo = 'js'; // 'wasm_worker' | 'wasm' | 'js'
        this.worker = null;
        this.wasmModulo = null;
        this.wasmEngine = null;
        this.wasmMemoria = null;
        this.inicializado = false;
        this.cargando = false;
        this.efectoActivo = 'particulas';

        // Telemetría de rendimiento
        this.stats = {
            fps: 60,
            frameTimeMs: 0,
            ultimoTimestamp: performance.now(),
            acumuladorFrames: 0,
            conteoFrames: 0,
            particulasContador: 0,
            lineasContador: 0,
            modoActivo: 'js',
        };

        // Estado de interacción
        this.mouse = { x: -1000, y: -1000, activo: false };
    }

    /**
     * Inicializa la fachada intentando activar OffscreenCanvas en Worker o WASM directo.
     * @param {HTMLCanvasElement|null} canvasElement - Elemento canvas opcional para transferir
     * @param {number} width - Ancho del viewport
     * @param {number} height - Alto del viewport
     * @param {number} particleCount - Cantidad de partículas deseadas
     */
    async inicializar(canvasElement = null, width = 1920, height = 1080, particleCount = 140) {
        if (this.inicializado || this.cargando) return;
        this.cargando = true;

        const tieneWasm = typeof WebAssembly === 'object' && typeof WebAssembly.instantiate === 'function';

        if (!tieneWasm) {
            console.warn('[Prig-Graficos] WebAssembly no soportado en este entorno. Operando en modo JS.');
            this._establecerModoJS();
            return;
        }

        // Intento 1: Desacoplamiento total con OffscreenCanvas y Web Worker
        if (canvasElement && typeof canvasElement.transferControlToOffscreen === 'function' && typeof Worker === 'function') {
            try {
                const offscreen = canvasElement.transferControlToOffscreen();
                this.worker = new Worker('/static/js/worker_motor_grafico.js', { type: 'module' });

                this.worker.onmessage = (e) => {
                    const msg = e.data;
                    if (!msg) return;
                    if (msg.tipo === 'OFFSCREEN_LISTO') {
                        this.modo = 'wasm_worker';
                        this.stats.modoActivo = 'wasm_worker (OffscreenCanvas + Rust SIMD)';
                        this.inicializado = true;
                        this.cargando = false;
                        console.info(`%c⚡ [Prig-Graficos] Motor gráfico Rust activo en Web Worker desacoplado (OffscreenCanvas, 0% CPU main thread)`, 'color: #00f0ff; font-weight: bold;');
                        window.dispatchEvent(new CustomEvent('prig_motor_grafico_cambio_modo', { detail: { modo: 'wasm_worker' } }));
                    } else if (msg.tipo === 'TELEMETRIA') {
                        this.stats.fps = msg.fps;
                        this.stats.frameTimeMs = msg.frameTimeMs;
                    } else if (msg.tipo === 'OFFSCREEN_ERROR') {
                        this._fallaDelWorker(msg.error);
                    }
                };

                this.worker.onerror = (err) => {
                    this._fallaDelWorker(err && err.message);
                };

                this.worker.postMessage({
                    tipo: 'INIT_OFFSCREEN',
                    canvas: offscreen,
                    width,
                    height,
                    particleCount,
                    efecto: this.efectoActivo,
                }, [offscreen]);

                return;
            } catch (errOffscreen) {
                console.info('[Prig-Graficos] OffscreenCanvas no transferible (posiblemente ya inicializado en main). Fallback a WASM en hilo principal.');
            }
        }

        // Intento 2: WASM en hilo principal con lectura Zero-Copy
        await this._inicializarWasmLocal(width, height, particleCount);
    }

    /**
     * El worker no pudo arrancar. El lienzo ya se le transfirió (transferControlToOffscreen), así que el hilo
     * principal no puede volver a dibujar en él: se pasa a modo JS y se avisa con `lienzoTransferido` para que quien
     * lo creó lo reemplace por uno nuevo.
     */
    _fallaDelWorker(motivo) {
        console.warn('[Prig-Graficos] El worker de OffscreenCanvas falló; se pasa a modo JS:', motivo);
        if (this.worker) {
            try { this.worker.terminate(); } catch (_) { /* ya terminado */ }
        }
        this.worker = null;
        this.lienzoTransferido = true;
        this.modo = 'js';
        this.stats.modoActivo = 'js (Canvas 2D)';
        this.inicializado = true;
        this.cargando = false;
        window.dispatchEvent(new CustomEvent('prig_motor_grafico_cambio_modo', { detail: { modo: 'js', lienzoTransferido: true } }));
    }

    async _inicializarWasmLocal(width, height, particleCount) {
        try {
            const moduloWasm = await import('/static/wasm/prig_render_wasm.js');
            const initWasm = moduloWasm.default;

            const wasmInstance = await initWasm('/static/wasm/prig_render_wasm_bg.wasm');

            this.wasmEngine = new moduloWasm.PrigEngineWasm(width, height, particleCount);
            this.wasmModulo = moduloWasm;
            this.wasmMemoria = wasmInstance.memory;

            this.modo = 'wasm';
            this.stats.modoActivo = 'wasm (Rust SIMD)';
            this.inicializado = true;
            this.cargando = false;

            console.info(`%c⚡ [Prig-Graficos] Motor gráfico Rust WebAssembly activo (memoria contigua SoA, 0 pausas GC)`, 'color: #00f0ff; font-weight: bold;');
            window.dispatchEvent(new CustomEvent('prig_motor_grafico_cambio_modo', { detail: { modo: 'wasm' } }));
        } catch (err) {
            console.warn('[Prig-Graficos] Fallback a motor JS nativo (WASM no disponible o error de carga):', err.message);
            this._establecerModoJS();
        }
    }

    _establecerModoJS() {
        this.modo = 'js';
        this.stats.modoActivo = 'js (Canvas 2D)';
        this.inicializado = true;
        this.cargando = false;
        window.dispatchEvent(new CustomEvent('prig_motor_grafico_cambio_modo', { detail: { modo: 'js' } }));
    }

    /**
     * Notifica un redimensionado de ventana al motor activo.
     */
    redimensionar(width, height) {
        if (this.modo === 'wasm_worker' && this.worker) {
            this.worker.postMessage({ tipo: 'RESIZE', width, height });
        } else if (this.modo === 'wasm' && this.wasmEngine) {
            this.wasmEngine.resize(width, height);
        }
    }

    /**
     * Actualiza las coordenadas del cursor del usuario.
     */
    actualizarMouse(x, y, activo = true) {
        this.mouse.x = x;
        this.mouse.y = y;
        this.mouse.activo = activo;

        if (this.modo === 'wasm_worker' && this.worker) {
            this.worker.postMessage({ tipo: 'MOUSE', x, y, activo });
        }
    }

    /**
     * Notifica cambio de efecto visual activo.
     */
    cambiarEfecto(efectoId) {
        this.efectoActivo = efectoId;
        if (this.modo === 'wasm_worker' && this.worker) {
            this.worker.postMessage({ tipo: 'CAMBIAR_EFECTO', efecto: efectoId });
        }
    }

    /**
     * Renderiza un fotograma del efecto de partículas cósmicas / red neuronal.
     */
    renderizarParticulas(ctx, width, height, dt, maxDist = 95.0) {
        // En modo wasm_worker, el worker renderiza autónomamente en su propio hilo
        if (this.modo === 'wasm_worker') {
            return;
        }

        const t0 = performance.now();

        if (this.modo === 'wasm' && this.wasmEngine && this.wasmMemoria) {
            this._renderizarParticulasWasm(ctx, width, height, dt, maxDist);
        } else {
            // Fallback JS
            if (window.motorMovimiento && typeof window.motorMovimiento._renderizarParticulasJS === 'function') {
                window.motorMovimiento._renderizarParticulasJS(ctx, width, height, dt);
            }
        }

        const t1 = performance.now();
        this._actualizarTelemetria(t1 - t0);
    }

    /**
     * Bucle de renderizado ultrarrápido con punteros a memoria Rust en hilo principal.
     */
    _renderizarParticulasWasm(ctx, width, height, dt, maxDist) {
        const engine = this.wasmEngine;

        engine.update_particles(dt, this.mouse.x, this.mouse.y, this.mouse.activo, maxDist);
        // El búfer DESPUÉS de actualizar: si la actualización hace crecer la memoria de WASM, el ArrayBuffer anterior
        // queda inválido y cualquier vista sobre él lanza una excepción en ese cuadro
        const memBuffer = this.wasmMemoria.buffer;

        const count = engine.get_particles_count();
        this.stats.particulasContador = count;

        const xArr = new Float32Array(memBuffer, engine.get_particles_x_ptr(), count);
        const yArr = new Float32Array(memBuffer, engine.get_particles_y_ptr(), count);
        const rArr = new Float32Array(memBuffer, engine.get_particles_radius_ptr(), count);
        const aArr = new Float32Array(memBuffer, engine.get_particles_alpha_ptr(), count);

        const linesPtr = engine.get_lines_ptr();
        const linesFloatCount = engine.get_lines_float_count();
        this.stats.lineasContador = Math.floor(linesFloatCount / 5);

        if (linesFloatCount > 0) {
            const linesArr = new Float32Array(memBuffer, linesPtr, linesFloatCount);
            ctx.lineWidth = 1.0;
            ctx.shadowBlur = 0;
            ctx.strokeStyle = 'rgba(0, 240, 255, 0.18)';
            ctx.beginPath();
            for (let i = 0; i < linesFloatCount; i += 5) {
                ctx.moveTo(linesArr[i], linesArr[i + 1]);
                ctx.lineTo(linesArr[i + 2], linesArr[i + 3]);
            }
            ctx.stroke();
        }

        ctx.shadowColor = '#00f0ff';
        ctx.shadowBlur = 6;
        for (let i = 0; i < count; i++) {
            ctx.fillStyle = `rgba(0, 240, 255, ${aArr[i]})`;
            ctx.beginPath();
            ctx.arc(xArr[i], yArr[i], rArr[i], 0, 6.2831853);
            ctx.fill();
        }
        ctx.shadowBlur = 0;
    }

    renderizarTesseract(ctx, width, height, dt, rotSpeed = 0.8) {
        if (this.modo === 'wasm_worker') return true;
        if (this.modo !== 'wasm' || !this.wasmEngine || !this.wasmMemoria) return false;

        const engine = this.wasmEngine;
        engine.update_tesseract(dt, rotSpeed);

        const count = engine.get_tesseract_lines_count();
        if (count === 0) return true;

        const linesArr = new Float32Array(this.wasmMemoria.buffer, engine.get_tesseract_lines_ptr(), count);

        ctx.lineWidth = 1.8;
        ctx.shadowColor = '#00f0ff';
        ctx.shadowBlur = 8;
        ctx.strokeStyle = '#00f0ff';

        ctx.beginPath();
        for (let i = 0; i < count; i += 5) {
            ctx.moveTo(linesArr[i], linesArr[i + 1]);
            ctx.lineTo(linesArr[i + 2], linesArr[i + 3]);
        }
        ctx.stroke();
        ctx.shadowBlur = 0;
        return true;
    }

    renderizarLorenz(ctx, width, height, dt) {
        if (this.modo === 'wasm_worker') return true;
        if (this.modo !== 'wasm' || !this.wasmEngine || !this.wasmMemoria) return false;

        const engine = this.wasmEngine;
        engine.update_lorenz(dt);

        const count = engine.get_lorenz_lines_count();
        if (count === 0) return true;

        const linesArr = new Float32Array(this.wasmMemoria.buffer, engine.get_lorenz_lines_ptr(), count);

        ctx.lineWidth = 1.5;
        ctx.shadowColor = '#89b4fa';
        ctx.shadowBlur = 5;

        for (let i = 0; i < count; i += 5) {
            const alpha = linesArr[i + 4];
            ctx.strokeStyle = `rgba(137, 180, 250, ${alpha})`;
            ctx.beginPath();
            ctx.moveTo(linesArr[i], linesArr[i + 1]);
            ctx.lineTo(linesArr[i + 2], linesArr[i + 3]);
            ctx.stroke();
        }
        ctx.shadowBlur = 0;
        return true;
    }

    renderizarBlackHole(ctx, width, height, dt) {
        if (this.modo === 'wasm_worker') return true;
        if (this.modo !== 'wasm' || !this.wasmEngine || !this.wasmMemoria) return false;

        const engine = this.wasmEngine;
        engine.update_black_hole(dt);

        const count = engine.get_black_hole_count();
        if (count === 0) return true;

        const arr = new Float32Array(this.wasmMemoria.buffer, engine.get_black_hole_ptr(), count);
        const cx = width * 0.5;
        const cy = height * 0.5;

        ctx.fillStyle = '#050508';
        ctx.beginPath();
        ctx.arc(cx, cy, 32.0, 0, 6.2831853);
        ctx.fill();

        ctx.shadowColor = '#00f0ff';
        ctx.shadowBlur = 6;
        for (let i = 0; i < count; i += 4) {
            ctx.fillStyle = '#00f0ff';
            ctx.beginPath();
            ctx.arc(arr[i], arr[i + 1], arr[i + 2], 0, 6.2831853);
            ctx.fill();
        }
        ctx.shadowBlur = 0;
        return true;
    }

    renderizarPoligonos(ctx, width, height, dt) {
        if (this.modo === 'wasm_worker') return true;
        if (this.modo !== 'wasm' || !this.wasmEngine || !this.wasmMemoria) return false;

        this.wasmEngine.polygons_update(dt);
        const count = this.wasmEngine.polygons_get_count();
        if (count === 0) return true;

        const arr = new Float32Array(this.wasmMemoria.buffer, this.wasmEngine.polygons_get_ptr(), count);
        ctx.lineWidth = 1.6;
        ctx.shadowBlur = 8;
        ctx.shadowColor = '#00f0ff';
        ctx.strokeStyle = '#00f0ff';

        ctx.beginPath();
        for (let i = 0; i < count; i += 5) {
            ctx.moveTo(arr[i], arr[i + 1]);
            ctx.lineTo(arr[i + 2], arr[i + 3]);
        }
        ctx.stroke();
        ctx.shadowBlur = 0;
        return true;
    }

    renderizarVortex(ctx, width, height, dt) {
        if (this.modo === 'wasm_worker') return true;
        if (this.modo !== 'wasm' || !this.wasmEngine || !this.wasmMemoria) return false;

        this.wasmEngine.vortex_update(dt);
        const count = this.wasmEngine.vortex_get_lines_count();
        if (count === 0) return true;

        const arr = new Float32Array(this.wasmMemoria.buffer, this.wasmEngine.vortex_get_lines_ptr(), count);
        ctx.lineWidth = 1.3;
        ctx.shadowBlur = 6;
        ctx.shadowColor = '#89b4fa';

        for (let i = 0; i < count; i += 5) {
            const alpha = arr[i + 4];
            ctx.strokeStyle = `rgba(137, 180, 250, ${alpha})`;
            ctx.beginPath();
            ctx.moveTo(arr[i], arr[i + 1]);
            ctx.lineTo(arr[i + 2], arr[i + 3]);
            ctx.stroke();
        }
        ctx.shadowBlur = 0;
        return true;
    }

    renderizarMatrix(ctx, width, height, dt) {
        if (this.modo === 'wasm_worker') return true;
        if (this.modo !== 'wasm' || !this.wasmEngine || !this.wasmMemoria) return false;

        this.wasmEngine.matrix_update(dt);
        const count = this.wasmEngine.matrix_get_count();
        if (count === 0) return true;

        const arr = new Float32Array(this.wasmMemoria.buffer, this.wasmEngine.matrix_get_ptr(), count);
        ctx.font = '13px monospace';

        for (let i = 0; i < count; i += 4) {
            const x = arr[i];
            const headY = arr[i + 1];
            const len = arr[i + 2];

            ctx.fillStyle = '#ffffff';
            ctx.shadowColor = '#a6e3a1';
            ctx.shadowBlur = 10;
            ctx.fillText('0', x, headY);

            ctx.shadowBlur = 0;
            for (let j = 1; j < len; j++) {
                const y = headY - j * 15;
                if (y > 0 && y < height) {
                    const alpha = (1.0 - j / len) * 0.85;
                    ctx.fillStyle = `rgba(166, 227, 161, ${alpha})`;
                    ctx.fillText((j % 2 === 0 ? '1' : '0'), x, y);
                }
            }
        }
        return true;
    }

    /**
     * Actualiza la cinemática analítica del Personaje y Drones en Rust WASM.
     * Retorna posición suave, balanceo de respiración, parpadeo y órbitas 3D.
     */
    actualizarActorYDrones(dt, cursorCodeX = 0, cursorCodeY = 0) {
        if (!this.wasmEngine || !this.wasmMemoria) return null;

        this.wasmEngine.actor_update(dt, cursorCodeX, cursorCodeY);
        this.wasmEngine.drones_update(dt);

        const ax = this.wasmEngine.actor_get_x();
        const ay = this.wasmEngine.actor_get_y();
        const breath = this.wasmEngine.actor_get_breath_offset();
        const blinking = this.wasmEngine.actor_is_blinking();
        const eyeDx = this.wasmEngine.actor_get_eye_dx();
        const eyeDy = this.wasmEngine.actor_get_eye_dy();

        const count = this.wasmEngine.drones_get_render_count();
        const drones = [];
        if (count > 0) {
            const arr = new Float32Array(this.wasmMemoria.buffer, this.wasmEngine.drones_get_render_ptr(), count);
            // El color viaja como los bits exactos de un u32 (f32::from_bits): se lee con una vista entera
            const bits = new Uint32Array(this.wasmMemoria.buffer, this.wasmEngine.drones_get_render_ptr(), count);
            for (let i = 0; i < count; i += 7) {
                drones.push({
                    x: arr[i],
                    y: arr[i + 1],
                    scale: arr[i + 2],
                    alpha: arr[i + 3],
                    zDepth: arr[i + 4],
                    isBehind: arr[i + 5] > 0.5,
                    colorU32: bits[i + 6]
                });
            }
        }

        return {
            x: ax,
            y: ay,
            breathOffset: breath,
            isBlinking: blinking,
            eyeDx: eyeDx,
            eyeDy: eyeDy,
            drones: drones
        };
    }

    /**
     * Calcula la relajación física de un grafo mediante Barnes-Hut O(N log N) en WebAssembly.
     */
    calcularLayoutGrafoBarnesHut(nodos, aristas, pasos = 35, dt = 0.04) {
        if (!this.wasmEngine || !this.wasmMemoria) return null;

        this.wasmEngine.graph_clear();
        const nodeMap = new Map();
        nodos.forEach((n, idx) => {
            const wasmIdx = this.wasmEngine.graph_add_node(n.x || (100 + idx * 30), n.y || (100 + idx * 30), n.mass || 1.0);
            nodeMap.set(n.id || idx, wasmIdx);
        });

        aristas.forEach(e => {
            const u = nodeMap.get(e.desde || e.source);
            const v = nodeMap.get(e.hacia || e.target);
            if (u !== undefined && v !== undefined) {
                this.wasmEngine.graph_add_edge(u, v, e.restLen || 80.0);
            }
        });

        for (let s = 0; s < pasos; s++) {
            this.wasmEngine.graph_step(dt, 1200.0, 0.05, 0.88);
        }

        const count = this.wasmEngine.graph_get_nodes_count();
        if (count === 0) return null;

        const posArr = new Float32Array(this.wasmMemoria.buffer, this.wasmEngine.graph_get_positions_ptr(), count * 2);
        return nodos.map((n, idx) => ({
            ...n,
            x: posArr[idx * 2],
            y: posArr[idx * 2 + 1]
        }));
    }

    _actualizarTelemetria(frameDurationMs) {
        this.stats.frameTimeMs = frameDurationMs;
        this.stats.conteoFrames++;

        const ahora = performance.now();
        if (ahora - this.stats.ultimoTimestamp >= 1000) {
            this.stats.fps = this.stats.conteoFrames;
            this.stats.conteoFrames = 0;
            this.stats.ultimoTimestamp = ahora;
        }
    }

    obtenerTelemetria() {
        return {
            modo: this.stats.modoActivo,
            fps: this.stats.fps,
            frameTimeMs: Number(this.stats.frameTimeMs.toFixed(2)),
            particulas: this.stats.particulasContador,
            conexiones: this.stats.lineasContador,
        };
    }
}

// Instancia singleton global
window.motorGraficoFachada = new MotorGraficoFachada();
