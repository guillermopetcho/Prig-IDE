/* tslint:disable */
/* eslint-disable */

/**
 * Motor gráfico principal en memoria WebAssembly.
 */
export class PrigEngineWasm {
    free(): void;
    [Symbol.dispose](): void;
    actor_get_breath_offset(): number;
    actor_get_eye_dx(): number;
    actor_get_eye_dy(): number;
    actor_get_x(): number;
    actor_get_y(): number;
    actor_is_blinking(): boolean;
    actor_set_state(state: number): void;
    actor_update(dt: number, cursor_code_x: number, cursor_code_y: number): void;
    drones_get_render_count(): number;
    drones_get_render_ptr(): number;
    drones_update(dt: number): void;
    get_black_hole_count(): number;
    get_black_hole_ptr(): number;
    get_cursor_smooth_x(): number;
    get_cursor_smooth_y(): number;
    get_lines_float_count(): number;
    get_lines_ptr(): number;
    get_lorenz_lines_count(): number;
    get_lorenz_lines_ptr(): number;
    get_particles_alpha_ptr(): number;
    get_particles_color_ptr(): number;
    get_particles_count(): number;
    get_particles_radius_ptr(): number;
    get_particles_x_ptr(): number;
    get_particles_y_ptr(): number;
    get_tesseract_lines_count(): number;
    get_tesseract_lines_ptr(): number;
    graph_add_edge(u: number, v: number, rest_len: number): void;
    graph_add_node(x: number, y: number, mass: number): number;
    graph_clear(): void;
    graph_get_nodes_count(): number;
    graph_get_positions_ptr(): number;
    graph_step(dt: number, repulsion_k: number, spring_k: number, damping: number): void;
    matrix_get_count(): number;
    matrix_get_ptr(): number;
    matrix_update(dt: number): void;
    constructor(width: number, height: number, particle_count: number);
    polygons_get_count(): number;
    polygons_get_ptr(): number;
    polygons_update(dt: number): void;
    /**
     * Redimensiona el lienzo de renderizado.
     */
    resize(width: number, height: number): void;
    update_black_hole(dt: number): void;
    /**
     * Actualiza el resorte analítico del cursor para seguimiento ultra suave.
     */
    update_cursor_spring(target_x: number, target_y: number, dt: number): void;
    update_lorenz(dt: number): void;
    /**
     * Actualiza la simulación de partículas y conexiones espaciales en O(N).
     */
    update_particles(dt: number, mouse_x: number, mouse_y: number, mouse_active: boolean, max_dist: number): void;
    update_tesseract(dt: number, rot_speed: number): void;
    vortex_get_lines_count(): number;
    vortex_get_lines_ptr(): number;
    vortex_update(dt: number): void;
}

export type InitInput = RequestInfo | URL | Response | BufferSource | WebAssembly.Module;

export interface InitOutput {
    readonly memory: WebAssembly.Memory;
    readonly __wbg_prigenginewasm_free: (a: number, b: number) => void;
    readonly prigenginewasm_actor_get_breath_offset: (a: number) => number;
    readonly prigenginewasm_actor_get_eye_dx: (a: number) => number;
    readonly prigenginewasm_actor_get_eye_dy: (a: number) => number;
    readonly prigenginewasm_actor_get_x: (a: number) => number;
    readonly prigenginewasm_actor_get_y: (a: number) => number;
    readonly prigenginewasm_actor_is_blinking: (a: number) => number;
    readonly prigenginewasm_actor_set_state: (a: number, b: number) => void;
    readonly prigenginewasm_actor_update: (a: number, b: number, c: number, d: number) => void;
    readonly prigenginewasm_drones_get_render_count: (a: number) => number;
    readonly prigenginewasm_drones_get_render_ptr: (a: number) => number;
    readonly prigenginewasm_drones_update: (a: number, b: number) => void;
    readonly prigenginewasm_get_black_hole_count: (a: number) => number;
    readonly prigenginewasm_get_black_hole_ptr: (a: number) => number;
    readonly prigenginewasm_get_cursor_smooth_x: (a: number) => number;
    readonly prigenginewasm_get_cursor_smooth_y: (a: number) => number;
    readonly prigenginewasm_get_lines_float_count: (a: number) => number;
    readonly prigenginewasm_get_lines_ptr: (a: number) => number;
    readonly prigenginewasm_get_lorenz_lines_count: (a: number) => number;
    readonly prigenginewasm_get_lorenz_lines_ptr: (a: number) => number;
    readonly prigenginewasm_get_particles_alpha_ptr: (a: number) => number;
    readonly prigenginewasm_get_particles_color_ptr: (a: number) => number;
    readonly prigenginewasm_get_particles_count: (a: number) => number;
    readonly prigenginewasm_get_particles_radius_ptr: (a: number) => number;
    readonly prigenginewasm_get_particles_x_ptr: (a: number) => number;
    readonly prigenginewasm_get_particles_y_ptr: (a: number) => number;
    readonly prigenginewasm_get_tesseract_lines_count: (a: number) => number;
    readonly prigenginewasm_get_tesseract_lines_ptr: (a: number) => number;
    readonly prigenginewasm_graph_add_edge: (a: number, b: number, c: number, d: number) => void;
    readonly prigenginewasm_graph_add_node: (a: number, b: number, c: number, d: number) => number;
    readonly prigenginewasm_graph_clear: (a: number) => void;
    readonly prigenginewasm_graph_get_nodes_count: (a: number) => number;
    readonly prigenginewasm_graph_get_positions_ptr: (a: number) => number;
    readonly prigenginewasm_graph_step: (a: number, b: number, c: number, d: number, e: number) => void;
    readonly prigenginewasm_matrix_get_count: (a: number) => number;
    readonly prigenginewasm_matrix_get_ptr: (a: number) => number;
    readonly prigenginewasm_matrix_update: (a: number, b: number) => void;
    readonly prigenginewasm_new: (a: number, b: number, c: number) => number;
    readonly prigenginewasm_polygons_get_count: (a: number) => number;
    readonly prigenginewasm_polygons_get_ptr: (a: number) => number;
    readonly prigenginewasm_polygons_update: (a: number, b: number) => void;
    readonly prigenginewasm_resize: (a: number, b: number, c: number) => void;
    readonly prigenginewasm_update_black_hole: (a: number, b: number) => void;
    readonly prigenginewasm_update_cursor_spring: (a: number, b: number, c: number, d: number) => void;
    readonly prigenginewasm_update_lorenz: (a: number, b: number) => void;
    readonly prigenginewasm_update_particles: (a: number, b: number, c: number, d: number, e: number, f: number) => void;
    readonly prigenginewasm_update_tesseract: (a: number, b: number, c: number) => void;
    readonly prigenginewasm_vortex_get_lines_count: (a: number) => number;
    readonly prigenginewasm_vortex_get_lines_ptr: (a: number) => number;
    readonly prigenginewasm_vortex_update: (a: number, b: number) => void;
}

export type SyncInitInput = BufferSource | WebAssembly.Module;

/**
 * Instantiates the given `module`, which can either be bytes or
 * a precompiled `WebAssembly.Module`.
 *
 * @param {{ module: SyncInitInput }} module - Passing `SyncInitInput` directly is deprecated.
 *
 * @returns {InitOutput}
 */
export function initSync(module: { module: SyncInitInput } | SyncInitInput): InitOutput;

/**
 * If `module_or_path` is {RequestInfo} or {URL}, makes a request and
 * for everything else, calls `WebAssembly.instantiate` directly.
 *
 * @param {{ module_or_path: InitInput | Promise<InitInput> }} module_or_path - Passing `InitInput` directly is deprecated.
 *
 * @returns {Promise<InitOutput>}
 */
export default function __wbg_init (module_or_path?: { module_or_path: InitInput | Promise<InitInput> } | InitInput | Promise<InitInput>): Promise<InitOutput>;
