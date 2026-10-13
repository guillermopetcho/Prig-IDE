/* @ts-self-types="./prig_render_wasm.d.ts" */

/**
 * Motor gráfico principal en memoria WebAssembly.
 */
export class PrigEngineWasm {
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        PrigEngineWasmFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_prigenginewasm_free(ptr, 0);
    }
    /**
     * @returns {number}
     */
    actor_get_breath_offset() {
        const ret = wasm.prigenginewasm_actor_get_breath_offset(this.__wbg_ptr);
        return ret;
    }
    /**
     * @returns {number}
     */
    actor_get_eye_dx() {
        const ret = wasm.prigenginewasm_actor_get_eye_dx(this.__wbg_ptr);
        return ret;
    }
    /**
     * @returns {number}
     */
    actor_get_eye_dy() {
        const ret = wasm.prigenginewasm_actor_get_eye_dy(this.__wbg_ptr);
        return ret;
    }
    /**
     * @returns {number}
     */
    actor_get_x() {
        const ret = wasm.prigenginewasm_actor_get_x(this.__wbg_ptr);
        return ret;
    }
    /**
     * @returns {number}
     */
    actor_get_y() {
        const ret = wasm.prigenginewasm_actor_get_y(this.__wbg_ptr);
        return ret;
    }
    /**
     * @returns {boolean}
     */
    actor_is_blinking() {
        const ret = wasm.prigenginewasm_actor_is_blinking(this.__wbg_ptr);
        return ret !== 0;
    }
    /**
     * @param {number} state
     */
    actor_set_state(state) {
        wasm.prigenginewasm_actor_set_state(this.__wbg_ptr, state);
    }
    /**
     * @param {number} dt
     * @param {number} cursor_code_x
     * @param {number} cursor_code_y
     */
    actor_update(dt, cursor_code_x, cursor_code_y) {
        wasm.prigenginewasm_actor_update(this.__wbg_ptr, dt, cursor_code_x, cursor_code_y);
    }
    /**
     * @returns {number}
     */
    drones_get_render_count() {
        const ret = wasm.prigenginewasm_drones_get_render_count(this.__wbg_ptr);
        return ret >>> 0;
    }
    /**
     * @returns {number}
     */
    drones_get_render_ptr() {
        const ret = wasm.prigenginewasm_drones_get_render_ptr(this.__wbg_ptr);
        return ret >>> 0;
    }
    /**
     * @param {number} dt
     */
    drones_update(dt) {
        wasm.prigenginewasm_drones_update(this.__wbg_ptr, dt);
    }
    /**
     * @returns {number}
     */
    get_black_hole_count() {
        const ret = wasm.prigenginewasm_get_black_hole_count(this.__wbg_ptr);
        return ret >>> 0;
    }
    /**
     * @returns {number}
     */
    get_black_hole_ptr() {
        const ret = wasm.prigenginewasm_get_black_hole_ptr(this.__wbg_ptr);
        return ret >>> 0;
    }
    /**
     * @returns {number}
     */
    get_cursor_smooth_x() {
        const ret = wasm.prigenginewasm_get_cursor_smooth_x(this.__wbg_ptr);
        return ret;
    }
    /**
     * @returns {number}
     */
    get_cursor_smooth_y() {
        const ret = wasm.prigenginewasm_get_cursor_smooth_y(this.__wbg_ptr);
        return ret;
    }
    /**
     * @returns {number}
     */
    get_lines_float_count() {
        const ret = wasm.prigenginewasm_get_lines_float_count(this.__wbg_ptr);
        return ret >>> 0;
    }
    /**
     * @returns {number}
     */
    get_lines_ptr() {
        const ret = wasm.prigenginewasm_get_lines_ptr(this.__wbg_ptr);
        return ret >>> 0;
    }
    /**
     * @returns {number}
     */
    get_lorenz_lines_count() {
        const ret = wasm.prigenginewasm_get_lorenz_lines_count(this.__wbg_ptr);
        return ret >>> 0;
    }
    /**
     * @returns {number}
     */
    get_lorenz_lines_ptr() {
        const ret = wasm.prigenginewasm_get_lorenz_lines_ptr(this.__wbg_ptr);
        return ret >>> 0;
    }
    /**
     * @returns {number}
     */
    get_particles_alpha_ptr() {
        const ret = wasm.prigenginewasm_get_particles_alpha_ptr(this.__wbg_ptr);
        return ret >>> 0;
    }
    /**
     * @returns {number}
     */
    get_particles_color_ptr() {
        const ret = wasm.prigenginewasm_get_particles_color_ptr(this.__wbg_ptr);
        return ret >>> 0;
    }
    /**
     * @returns {number}
     */
    get_particles_count() {
        const ret = wasm.prigenginewasm_get_particles_count(this.__wbg_ptr);
        return ret >>> 0;
    }
    /**
     * @returns {number}
     */
    get_particles_radius_ptr() {
        const ret = wasm.prigenginewasm_get_particles_radius_ptr(this.__wbg_ptr);
        return ret >>> 0;
    }
    /**
     * @returns {number}
     */
    get_particles_x_ptr() {
        const ret = wasm.prigenginewasm_get_particles_x_ptr(this.__wbg_ptr);
        return ret >>> 0;
    }
    /**
     * @returns {number}
     */
    get_particles_y_ptr() {
        const ret = wasm.prigenginewasm_get_particles_y_ptr(this.__wbg_ptr);
        return ret >>> 0;
    }
    /**
     * @returns {number}
     */
    get_tesseract_lines_count() {
        const ret = wasm.prigenginewasm_get_tesseract_lines_count(this.__wbg_ptr);
        return ret >>> 0;
    }
    /**
     * @returns {number}
     */
    get_tesseract_lines_ptr() {
        const ret = wasm.prigenginewasm_get_tesseract_lines_ptr(this.__wbg_ptr);
        return ret >>> 0;
    }
    /**
     * @param {number} u
     * @param {number} v
     * @param {number} rest_len
     */
    graph_add_edge(u, v, rest_len) {
        wasm.prigenginewasm_graph_add_edge(this.__wbg_ptr, u, v, rest_len);
    }
    /**
     * @param {number} x
     * @param {number} y
     * @param {number} mass
     * @returns {number}
     */
    graph_add_node(x, y, mass) {
        const ret = wasm.prigenginewasm_graph_add_node(this.__wbg_ptr, x, y, mass);
        return ret >>> 0;
    }
    graph_clear() {
        wasm.prigenginewasm_graph_clear(this.__wbg_ptr);
    }
    /**
     * @returns {number}
     */
    graph_get_nodes_count() {
        const ret = wasm.prigenginewasm_graph_get_nodes_count(this.__wbg_ptr);
        return ret >>> 0;
    }
    /**
     * @returns {number}
     */
    graph_get_positions_ptr() {
        const ret = wasm.prigenginewasm_graph_get_positions_ptr(this.__wbg_ptr);
        return ret >>> 0;
    }
    /**
     * @param {number} dt
     * @param {number} repulsion_k
     * @param {number} spring_k
     * @param {number} damping
     */
    graph_step(dt, repulsion_k, spring_k, damping) {
        wasm.prigenginewasm_graph_step(this.__wbg_ptr, dt, repulsion_k, spring_k, damping);
    }
    /**
     * @returns {number}
     */
    matrix_get_count() {
        const ret = wasm.prigenginewasm_matrix_get_count(this.__wbg_ptr);
        return ret >>> 0;
    }
    /**
     * @returns {number}
     */
    matrix_get_ptr() {
        const ret = wasm.prigenginewasm_matrix_get_ptr(this.__wbg_ptr);
        return ret >>> 0;
    }
    /**
     * @param {number} dt
     */
    matrix_update(dt) {
        wasm.prigenginewasm_matrix_update(this.__wbg_ptr, dt);
    }
    /**
     * @param {number} width
     * @param {number} height
     * @param {number} particle_count
     */
    constructor(width, height, particle_count) {
        const ret = wasm.prigenginewasm_new(width, height, particle_count);
        this.__wbg_ptr = ret;
        PrigEngineWasmFinalization.register(this, this.__wbg_ptr, this);
        return this;
    }
    /**
     * @returns {number}
     */
    polygons_get_count() {
        const ret = wasm.prigenginewasm_polygons_get_count(this.__wbg_ptr);
        return ret >>> 0;
    }
    /**
     * @returns {number}
     */
    polygons_get_ptr() {
        const ret = wasm.prigenginewasm_polygons_get_ptr(this.__wbg_ptr);
        return ret >>> 0;
    }
    /**
     * @param {number} dt
     */
    polygons_update(dt) {
        wasm.prigenginewasm_polygons_update(this.__wbg_ptr, dt);
    }
    /**
     * Redimensiona el lienzo de renderizado.
     * @param {number} width
     * @param {number} height
     */
    resize(width, height) {
        wasm.prigenginewasm_resize(this.__wbg_ptr, width, height);
    }
    /**
     * @param {number} dt
     */
    update_black_hole(dt) {
        wasm.prigenginewasm_update_black_hole(this.__wbg_ptr, dt);
    }
    /**
     * Actualiza el resorte analítico del cursor para seguimiento ultra suave.
     * @param {number} target_x
     * @param {number} target_y
     * @param {number} dt
     */
    update_cursor_spring(target_x, target_y, dt) {
        wasm.prigenginewasm_update_cursor_spring(this.__wbg_ptr, target_x, target_y, dt);
    }
    /**
     * @param {number} dt
     */
    update_lorenz(dt) {
        wasm.prigenginewasm_update_lorenz(this.__wbg_ptr, dt);
    }
    /**
     * Actualiza la simulación de partículas y conexiones espaciales en O(N).
     * @param {number} dt
     * @param {number} mouse_x
     * @param {number} mouse_y
     * @param {boolean} mouse_active
     * @param {number} max_dist
     */
    update_particles(dt, mouse_x, mouse_y, mouse_active, max_dist) {
        wasm.prigenginewasm_update_particles(this.__wbg_ptr, dt, mouse_x, mouse_y, mouse_active, max_dist);
    }
    /**
     * @param {number} dt
     * @param {number} rot_speed
     */
    update_tesseract(dt, rot_speed) {
        wasm.prigenginewasm_update_tesseract(this.__wbg_ptr, dt, rot_speed);
    }
    /**
     * @returns {number}
     */
    vortex_get_lines_count() {
        const ret = wasm.prigenginewasm_vortex_get_lines_count(this.__wbg_ptr);
        return ret >>> 0;
    }
    /**
     * @returns {number}
     */
    vortex_get_lines_ptr() {
        const ret = wasm.prigenginewasm_vortex_get_lines_ptr(this.__wbg_ptr);
        return ret >>> 0;
    }
    /**
     * @param {number} dt
     */
    vortex_update(dt) {
        wasm.prigenginewasm_vortex_update(this.__wbg_ptr, dt);
    }
}
if (Symbol.dispose) PrigEngineWasm.prototype[Symbol.dispose] = PrigEngineWasm.prototype.free;
function __wbg_get_imports() {
    const import0 = {
        __proto__: null,
        __wbg___wbindgen_throw_41e9ee4f547fc59a: function(arg0, arg1) {
            throw new Error(getStringFromWasm0(arg0, arg1));
        },
    };
    return {
        __proto__: null,
        "./prig_render_wasm_bg.js": import0,
    };
}

const PrigEngineWasmFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_prigenginewasm_free(ptr, 1));

function getStringFromWasm0(ptr, len) {
    return decodeText(ptr >>> 0, len);
}

let cachedUint8ArrayMemory0 = null;
function getUint8ArrayMemory0() {
    if (cachedUint8ArrayMemory0 === null || cachedUint8ArrayMemory0.byteLength === 0) {
        cachedUint8ArrayMemory0 = new Uint8Array(wasm.memory.buffer);
    }
    return cachedUint8ArrayMemory0;
}

let cachedTextDecoder = new TextDecoder('utf-8', { ignoreBOM: true, fatal: true });
cachedTextDecoder.decode();
const MAX_SAFARI_DECODE_BYTES = 2146435072;
let numBytesDecoded = 0;
function decodeText(ptr, len) {
    numBytesDecoded += len;
    if (numBytesDecoded >= MAX_SAFARI_DECODE_BYTES) {
        cachedTextDecoder = new TextDecoder('utf-8', { ignoreBOM: true, fatal: true });
        cachedTextDecoder.decode();
        numBytesDecoded = len;
    }
    return cachedTextDecoder.decode(getUint8ArrayMemory0().subarray(ptr, ptr + len));
}

let wasmModule, wasmInstance, wasm;
function __wbg_finalize_init(instance, module) {
    wasmInstance = instance;
    wasm = instance.exports;
    wasmModule = module;
    cachedUint8ArrayMemory0 = null;
    return wasm;
}

async function __wbg_load(module, imports) {
    if (typeof Response === 'function' && module instanceof Response) {
        if (!module.ok) {
            throw new Error(`failed to fetch Wasm: ${module.status} ${module.statusText} fetching '${module.url}'`);
        }

        if (typeof WebAssembly.instantiateStreaming === 'function') {
            try {
                return await WebAssembly.instantiateStreaming(module, imports);
            } catch (e) {
                const validResponse = expectedResponseType(module.type);

                if (validResponse && module.headers.get('Content-Type') !== 'application/wasm') {
                    console.warn("`WebAssembly.instantiateStreaming` failed because your server does not serve Wasm with `application/wasm` MIME type. Falling back to `WebAssembly.instantiate` which is slower. Original error:\n", e);

                } else { throw e; }
            }
        }

        const bytes = await module.arrayBuffer();
        return await WebAssembly.instantiate(bytes, imports);
    } else {
        const instance = await WebAssembly.instantiate(module, imports);

        if (instance instanceof WebAssembly.Instance) {
            return { instance, module };
        } else {
            return instance;
        }
    }

    function expectedResponseType(type) {
        switch (type) {
            case 'basic': case 'cors': case 'default': return true;
        }
        return false;
    }
}

function initSync(module) {
    if (wasm !== undefined) return wasm;


    if (module !== undefined) {
        if (Object.getPrototypeOf(module) === Object.prototype) {
            ({module} = module)
        } else {
            console.warn('using deprecated parameters for `initSync()`; pass a single object instead')
        }
    }

    const imports = __wbg_get_imports();
    if (!(module instanceof WebAssembly.Module)) {
        module = new WebAssembly.Module(module);
    }
    const instance = new WebAssembly.Instance(module, imports);
    return __wbg_finalize_init(instance, module);
}

async function __wbg_init(module_or_path) {
    if (wasm !== undefined) return wasm;


    if (module_or_path !== undefined) {
        if (Object.getPrototypeOf(module_or_path) === Object.prototype) {
            ({module_or_path} = module_or_path)
        } else {
            console.warn('using deprecated parameters for the initialization function; pass a single object instead')
        }
    }

    if (module_or_path === undefined) {
        module_or_path = new URL('prig_render_wasm_bg.wasm', import.meta.url);
    }
    const imports = __wbg_get_imports();

    if (typeof module_or_path === 'string' || (typeof Request === 'function' && module_or_path instanceof Request) || (typeof URL === 'function' && module_or_path instanceof URL)) {
        module_or_path = fetch(module_or_path);
    }

    const { instance, module } = await __wbg_load(await module_or_path, imports);

    return __wbg_finalize_init(instance, module);
}

export { initSync, __wbg_init as default };
