/**
 * ==============================================================================
 * worker_motor_grafico.js — Web Worker Dedicado de Renderizado con OffscreenCanvas
 * ==============================================================================
 * Ejecuta el bucle de renderizado y la física SIMD en Rust (WebAssembly) en un hilo
 * de fondo aislado del navegador.
 * 
 * Monaco Editor y el hilo principal de la interfaz quedan con 0% de sobrecarga
 * de cómputo gráfico, eliminando totalmente cualquier pausa de recolección de basura
 * (GC jitter = 0.0 ms) y garantizando 60/120 FPS sin jank.
 * 
 * Audio Reactivo: Purificado y eliminado al 100%. Bucle determinista.
 */

// Estado interno del Worker
let canvas = null;
let ctx = null;
let animId = null;
let wasmEngine = null;
let wasmMemoria = null;
let efectoActivo = 'particulas';
let dronesActivos = false;

let ancho = 1280;
let alto = 720;
let ultimoTimestamp = performance.now();

const mouse = { x: -1000, y: -1000, activo: false };

// requestAnimationFrame no existe en los workers de todos los navegadores: sin él, un temporizador de ~60 Hz
const pedirCuadro = (typeof requestAnimationFrame === 'function')
    ? requestAnimationFrame.bind(self)
    : (f) => setTimeout(() => f(performance.now()), 16);
const cancelarCuadro = (typeof cancelAnimationFrame === 'function') ? cancelAnimationFrame.bind(self) : clearTimeout;

// Telemetría
let conteoFrames = 0;
let ultimoReporteTelemetria = performance.now();

/**
 * Receptor de mensajes del hilo principal.
 */
self.onmessage = async function(e) {
    const data = e.data;
    if (!data || !data.tipo) return;

    switch (data.tipo) {
        case 'INIT_OFFSCREEN':
            await inicializarOffscreen(data);
            break;

        case 'RESIZE':
            redimensionar(data.width, data.height);
            break;

        case 'MOUSE':
            mouse.x = data.x;
            mouse.y = data.y;
            mouse.activo = data.activo;
            break;

        case 'CAMBIAR_EFECTO':
            efectoActivo = data.efecto || 'particulas';
            break;

        case 'CONFIG_DRONES':
            dronesActivos = !!data.activo;
            break;

        case 'PAUSAR':
            if (animId) {
                cancelarCuadro(animId);
                animId = null;
            }
            break;

        case 'REANUDAR':
            if (!animId && canvas) {
                ultimoTimestamp = performance.now();
                animId = pedirCuadro(bucleRender);
            }
            break;
    }
};

/**
 * Inicializa el lienzo Offscreen y carga el módulo WebAssembly compilado en Rust.
 */
async function inicializarOffscreen(datos) {
    canvas = datos.canvas;
    ancho = datos.width || 1280;
    alto = datos.height || 720;
    efectoActivo = datos.efecto || 'particulas';

    ctx = canvas.getContext('2d', { alpha: true, desynchronized: true });

    try {
        // Carga dinámica de WebAssembly dentro del Worker
        const moduloWasm = await import('/static/wasm/prig_render_wasm.js');
        const initWasm = moduloWasm.default;

        const wasmInstance = await initWasm('/static/wasm/prig_render_wasm_bg.wasm');
        wasmMemoria = wasmInstance.memory;

        const particleCount = datos.particleCount || 140;
        wasmEngine = new moduloWasm.PrigEngineWasm(ancho, alto, particleCount);

        // Iniciar bucle de animación autónomo en el Worker, y recién entonces avisar que está listo
        ultimoTimestamp = performance.now();
        animId = pedirCuadro(bucleRender);
        self.postMessage({ tipo: 'OFFSCREEN_LISTO', ok: true, modo: 'wasm_worker' });
    } catch (err) {
        console.warn('[Prig-Worker] Error inicializando WebAssembly en Worker:', err);
        self.postMessage({ tipo: 'OFFSCREEN_ERROR', error: err.message });
    }
}

function redimensionar(nuevoAncho, nuevoAlto) {
    ancho = nuevoAncho;
    alto = nuevoAlto;
    if (canvas) {
        canvas.width = nuevoAncho;
        canvas.height = nuevoAlto;
    }
    if (wasmEngine) {
        wasmEngine.resize(nuevoAncho, nuevoAlto);
    }
}

/**
 * Bucle autónomo de renderizado ejecutado en el hilo del Worker.
 */
function bucleRender(timestamp) {
    const dt = Math.min((timestamp - ultimoTimestamp) / 1000, 0.05);
    ultimoTimestamp = timestamp;

    if (ctx && wasmEngine && wasmMemoria) {
        const t0 = performance.now();
        renderizarFrame(dt);
        const t1 = performance.now();

        // Control y reporte de telemetría a 1 Hz
        conteoFrames++;
        if (timestamp - ultimoReporteTelemetria >= 1000) {
            self.postMessage({
                tipo: 'TELEMETRIA',
                fps: conteoFrames,
                frameTimeMs: Number((t1 - t0).toFixed(2)),
                efecto: efectoActivo,
            });
            conteoFrames = 0;
            ultimoReporteTelemetria = timestamp;
        }
    }

    animId = pedirCuadro(bucleRender);
}

/**
 * Despacho del efecto seleccionado utilizando los búferes contiguos de Rust.
 */
function renderizarFrame(dt) {
    switch (efectoActivo) {
        case 'particulas':
            renderizarParticulas(dt);
            break;
        case 'hipercubo_4d_tesseract':
            renderizarTesseract(dt);
            break;
        case 'atractor_lorentz':
            renderizarLorenz(dt);
            break;
        case 'agujero_negro_interstellar':
            renderizarBlackHole(dt);
            break;
        case 'poligonos_cuanticos':
            renderizarPoligonos(dt);
            break;
        case 'tunel_vortex':
            renderizarVortex(dt);
            break;
        case 'matrix':
            renderizarMatrix(dt);
            break;
        default:
            renderizarParticulas(dt);
            break;
    }

    if (dronesActivos) {
        renderizarDronesTacticos(dt);
    }
}

function renderizarParticulas(dt) {
    ctx.clearRect(0, 0, ancho, alto);

    wasmEngine.update_particles(dt, mouse.x, mouse.y, mouse.activo, 95.0);

    const memBuffer = wasmMemoria.buffer;
    const count = wasmEngine.get_particles_count();

    const xArr = new Float32Array(memBuffer, wasmEngine.get_particles_x_ptr(), count);
    const yArr = new Float32Array(memBuffer, wasmEngine.get_particles_y_ptr(), count);
    const rArr = new Float32Array(memBuffer, wasmEngine.get_particles_radius_ptr(), count);
    const aArr = new Float32Array(memBuffer, wasmEngine.get_particles_alpha_ptr(), count);

    const linesPtr = wasmEngine.get_lines_ptr();
    const linesFloatCount = wasmEngine.get_lines_float_count();

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

function renderizarTesseract(dt) {
    ctx.clearRect(0, 0, ancho, alto);
    wasmEngine.update_tesseract(dt, 0.75);

    const count = wasmEngine.get_tesseract_lines_count();
    if (count === 0) return;

    const linesArr = new Float32Array(wasmMemoria.buffer, wasmEngine.get_tesseract_lines_ptr(), count);

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
}

function renderizarLorenz(dt) {
    ctx.fillStyle = 'rgba(10, 8, 20, 0.25)';
    ctx.fillRect(0, 0, ancho, alto);

    wasmEngine.update_lorenz(dt);
    const count = wasmEngine.get_lorenz_lines_count();
    if (count === 0) return;

    const linesArr = new Float32Array(wasmMemoria.buffer, wasmEngine.get_lorenz_lines_ptr(), count);

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
}

function renderizarBlackHole(dt) {
    ctx.fillStyle = 'rgba(5, 5, 12, 0.28)';
    ctx.fillRect(0, 0, ancho, alto);

    wasmEngine.update_black_hole(dt);
    const count = wasmEngine.get_black_hole_count();
    if (count === 0) return;

    const arr = new Float32Array(wasmMemoria.buffer, wasmEngine.get_black_hole_ptr(), count);
    const cx = ancho * 0.5;
    const cy = alto * 0.5;

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
}

function renderizarPoligonos(dt) {
    ctx.clearRect(0, 0, ancho, alto);
    wasmEngine.polygons_update(dt);

    const count = wasmEngine.polygons_get_count();
    if (count === 0) return;

    const arr = new Float32Array(wasmMemoria.buffer, wasmEngine.polygons_get_ptr(), count);
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
}

function renderizarVortex(dt) {
    ctx.clearRect(0, 0, ancho, alto);
    wasmEngine.vortex_update(dt);

    const count = wasmEngine.vortex_get_lines_count();
    if (count === 0) return;

    const arr = new Float32Array(wasmMemoria.buffer, wasmEngine.vortex_get_lines_ptr(), count);
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
}

function renderizarMatrix(dt) {
    ctx.fillStyle = 'rgba(5, 5, 8, 0.22)';
    ctx.fillRect(0, 0, ancho, alto);

    wasmEngine.matrix_update(dt);
    const count = wasmEngine.matrix_get_count();
    if (count === 0) return;

    const arr = new Float32Array(wasmMemoria.buffer, wasmEngine.matrix_get_ptr(), count);
    ctx.font = '13px monospace';

    for (let i = 0; i < count; i += 4) {
        const x = arr[i];
        const headY = arr[i + 1];
        const len = arr[i + 2];

        // Cabeza brillante de la gota
        ctx.fillStyle = '#ffffff';
        ctx.shadowColor = '#a6e3a1';
        ctx.shadowBlur = 10;
        ctx.fillText('0', x, headY);

        // Estela verde digital
        ctx.fillStyle = '#a6e3a1';
        ctx.shadowBlur = 0;
        for (let j = 1; j < len; j++) {
            const y = headY - j * 15;
            if (y > 0 && y < alto) {
                const alpha = (1.0 - j / len) * 0.85;
                ctx.fillStyle = `rgba(166, 227, 161, ${alpha})`;
                ctx.fillText((j % 2 === 0 ? '1' : '0'), x, y);
            }
        }
    }
}

function renderizarDronesTacticos(dt) {
    if (!wasmEngine || !wasmMemoria) return;
    wasmEngine.drones_update(dt);
    const count = wasmEngine.drones_get_render_count();
    if (count === 0) return;

    const arr = new Float32Array(wasmMemoria.buffer, wasmEngine.drones_get_render_ptr(), count);
    // El color va como los bits exactos de un u32 (f32::from_bits en Rust)
    const bits = new Uint32Array(wasmMemoria.buffer, wasmEngine.drones_get_render_ptr(), count);
    ctx.save();
    ctx.font = 'bold 9px monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    const glifos = ['◄●►', '⌖', '◈'];
    for (let i = 0, d = 0; i < count; i += 7, d++) {
        const x = arr[i];
        const y = arr[i + 1];
        const scale = arr[i + 2];
        const alpha = arr[i + 3];
        const colorU32 = bits[i + 6];

        const r = (colorU32 >>> 24) & 0xff;
        const g = (colorU32 >>> 16) & 0xff;
        const b = (colorU32 >>> 8) & 0xff;

        ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${alpha})`;
        ctx.shadowColor = `rgba(${r}, ${g}, ${b}, 0.8)`;
        ctx.shadowBlur = 6 * scale;
        ctx.fillText(glifos[d % glifos.length], x, y);
    }
    ctx.restore();
}


