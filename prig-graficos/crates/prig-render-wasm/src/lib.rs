//! Prig Render WASM — Enlace de WebAssembly de alto rendimiento para el motor visual.

use wasm_bindgen::prelude::*;
use prig_render_core::{
    algebra::{project_3d_to_screen, Vec3, Vec4},
    atractores::{BlackHoleSystem, LorenzAttractor},
    barnes_hut::GraphLayoutSystem,
    particion_espacial::SpatialGrid1D,
    particulas::ParticleSystem,
    spring_physics::Spring2D,
};
use prig_ascii_engine::{CharacterActor, DroneFleet};

pub mod efectos;

use efectos::{MatrixRainSystem, QuantumPolygonSystem, VortexTunnelSystem};

/// Motor gráfico principal en memoria WebAssembly.
#[wasm_bindgen]
pub struct PrigEngineWasm {
    particles: ParticleSystem,
    grid: SpatialGrid1D,
    lorenz: LorenzAttractor,
    black_hole: BlackHoleSystem,
    spring_cursor: Spring2D,
    graph_layout: GraphLayoutSystem,
    graph_positions: Vec<f32>,
    polygons: QuantumPolygonSystem,
    vortex: VortexTunnelSystem,
    matrix_rain: MatrixRainSystem,
    character: CharacterActor,
    drones: DroneFleet,
    drone_render_buffer: Vec<f32>, // [x, y, scale, alpha, z_depth, detrás (0/1), bits del color u32] por dron
    // Búferes contiguos para proyección de líneas 4D / 3D
    tesseract_lines: Vec<f32>, // [x1, y1, x2, y2, alpha, ...]
    lorenz_lines: Vec<f32>,
    black_hole_render: Vec<f32>, // [x, y, radius, color_u32, ...]
    angle_xw: f32,
    angle_yw: f32,
    angle_zw: f32,
    width: f32,
    height: f32,
}

#[wasm_bindgen]
impl PrigEngineWasm {
    #[wasm_bindgen(constructor)]
    pub fn new(width: f32, height: f32, particle_count: usize) -> Self {
        let count = particle_count.clamp(10, 2000);
        let particles = ParticleSystem::new(count, width, height, 42);
        let grid = SpatialGrid1D::new(110.0, count, width, height);
        let lorenz = LorenzAttractor::new(Vec3::new(0.1, 0.0, 0.0), 300);
        let black_hole = BlackHoleSystem::new(320, 25.0);
        let spring_cursor = Spring2D::new(width * 0.5, height * 0.5, 4.0, 1.0);
        let graph_layout = GraphLayoutSystem::new(width, height);
        let polygons = QuantumPolygonSystem::new(24, width, height, 77);
        let vortex = VortexTunnelSystem::new(width, height);
        let matrix_rain = MatrixRainSystem::new(15.0, width, height, 88);
        let character = CharacterActor::new(width, height);
        let drones = DroneFleet::new();

        Self {
            particles,
            grid,
            lorenz,
            black_hole,
            spring_cursor,
            graph_layout,
            graph_positions: Vec::with_capacity(512 * 2),
            polygons,
            vortex,
            matrix_rain,
            character,
            drones,
            drone_render_buffer: Vec::with_capacity(3 * 6),
            tesseract_lines: Vec::with_capacity(32 * 5),
            lorenz_lines: Vec::with_capacity(300 * 5),
            black_hole_render: Vec::with_capacity(320 * 4),
            angle_xw: 0.0,
            angle_yw: 0.0,
            angle_zw: 0.0,
            width,
            height,
        }
    }

    /// Redimensiona el lienzo de renderizado.
    pub fn resize(&mut self, width: f32, height: f32) {
        // Un lienzo oculto mide 0×0: todos los sistemas reciben el tamaño ya acotado
        let (width, height) = (width.max(1.0), height.max(1.0));
        self.width = width;
        self.height = height;
        self.particles.resize(width, height);
        self.grid.resize(width, height, self.particles.count);
        self.polygons.resize(width, height);
        self.vortex.resize(width, height);
        self.matrix_rain.resize(width, height);
        self.character.resize(width, height);
    }

    /// Actualiza el resorte analítico del cursor para seguimiento ultra suave.
    pub fn update_cursor_spring(&mut self, target_x: f32, target_y: f32, dt: f32) {
        self.spring_cursor.set_target(target_x, target_y);
        self.spring_cursor.update(dt);
    }

    pub fn get_cursor_smooth_x(&self) -> f32 {
        self.spring_cursor.x
    }

    pub fn get_cursor_smooth_y(&self) -> f32 {
        self.spring_cursor.y
    }

    /// Actualiza la simulación de partículas y conexiones espaciales en O(N).
    pub fn update_particles(&mut self, dt: f32, mouse_x: f32, mouse_y: f32, mouse_active: bool, max_dist: f32) {
        self.particles.update(dt, mouse_x, mouse_y, mouse_active);
        self.grid.index_particles(&self.particles.x, &self.particles.y, self.particles.count);
        self.grid.find_connections(&self.particles.x, &self.particles.y, self.particles.count, max_dist, 0.85);
    }

    // --- Punteros a memoria lineal para CERO COPIAS desde JavaScript ---

    pub fn get_particles_x_ptr(&self) -> *const f32 {
        self.particles.x.as_ptr()
    }

    pub fn get_particles_y_ptr(&self) -> *const f32 {
        self.particles.y.as_ptr()
    }

    pub fn get_particles_radius_ptr(&self) -> *const f32 {
        self.particles.radius.as_ptr()
    }

    pub fn get_particles_color_ptr(&self) -> *const u32 {
        self.particles.color_rgba.as_ptr()
    }

    pub fn get_particles_alpha_ptr(&self) -> *const f32 {
        self.particles.alpha.as_ptr()
    }

    pub fn get_particles_count(&self) -> usize {
        self.particles.count
    }

    pub fn get_lines_ptr(&self) -> *const f32 {
        self.grid.lines_buffer.as_ptr()
    }

    pub fn get_lines_float_count(&self) -> usize {
        self.grid.lines_buffer.len()
    }

    // --- Efecto 4D Tesseract hiperdimensional puro ---

    pub fn update_tesseract(&mut self, dt: f32, rot_speed: f32) {
        self.angle_xw += rot_speed * dt * 0.7;
        self.angle_yw += rot_speed * dt * 0.9;
        self.angle_zw += rot_speed * dt * 0.4;

        self.tesseract_lines.clear();

        // Los 16 vértices del hipercubo (+-1, +-1, +-1, +-1)
        let mut vertices_4d = [Vec4::new(0.0, 0.0, 0.0, 0.0); 16];
        for i in 0..16 {
            let x = if (i & 1) != 0 { 1.0 } else { -1.0 };
            let y = if (i & 2) != 0 { 1.0 } else { -1.0 };
            let z = if (i & 4) != 0 { 1.0 } else { -1.0 };
            let w = if (i & 8) != 0 { 1.0 } else { -1.0 };
            let v = Vec4::new(x, y, z, w)
                .rotate_xw(self.angle_xw)
                .rotate_yw(self.angle_yw)
                .rotate_zw(self.angle_zw);
            vertices_4d[i] = v;
        }

        // Proyección estereográfica 4D -> 3D y luego perspectiva 3D -> 2D
        let cx = self.width * 0.5;
        let cy = self.height * 0.5;
        let scale = self.height.min(self.width) * 0.38;

        let mut proj_2d = [prig_render_core::Vec2::new(0.0, 0.0); 16];
        for (i, v4) in vertices_4d.iter().enumerate() {
            let p3 = v4.project_to_3d(2.4);
            let (p2, _) = project_3d_to_screen(p3, 3.2, cx, cy, scale);
            proj_2d[i] = p2;
        }

        // 32 aristas conectando vértices que difieren en exactamente 1 bit
        for i in 0..16 {
            for bit in 0..4 {
                let j = i ^ (1 << bit);
                if j > i {
                    self.tesseract_lines.push(proj_2d[i].x);
                    self.tesseract_lines.push(proj_2d[i].y);
                    self.tesseract_lines.push(proj_2d[j].x);
                    self.tesseract_lines.push(proj_2d[j].y);
                    // Profundidad alfa según coordenada w promedio
                    let avg_w = (vertices_4d[i].w + vertices_4d[j].w) * 0.5;
                    let alpha = ((avg_w + 1.5) / 3.0).clamp(0.2, 0.95);
                    self.tesseract_lines.push(alpha);
                }
            }
        }
    }

    pub fn get_tesseract_lines_ptr(&self) -> *const f32 {
        self.tesseract_lines.as_ptr()
    }

    pub fn get_tesseract_lines_count(&self) -> usize {
        self.tesseract_lines.len()
    }

    // --- Efecto Atractor de Lorentz RK4 puro ---

    pub fn update_lorenz(&mut self, dt: f32) {
        // Ejecuta 3 substeps de RK4 para estabilidad suave
        for _ in 0..3 {
            self.lorenz.step(dt * 0.6);
        }

        self.lorenz_lines.clear();
        let trail = &self.lorenz.trail;
        if trail.len() < 2 {
            return;
        }

        let cx = self.width * 0.5;
        let cy = self.height * 0.5;
        let scale = self.height.min(self.width) * 0.022;

        for i in 0..(trail.len() - 1) {
            let (p1, _) = project_3d_to_screen(trail[i], 80.0, cx, cy, scale);
            let (p2, _) = project_3d_to_screen(trail[i + 1], 80.0, cx, cy, scale);
            let alpha = ((i as f32) / (trail.len() as f32)).clamp(0.1, 0.9);

            self.lorenz_lines.push(p1.x);
            self.lorenz_lines.push(p1.y);
            self.lorenz_lines.push(p2.x);
            self.lorenz_lines.push(p2.y);
            self.lorenz_lines.push(alpha);
        }
    }

    pub fn get_lorenz_lines_ptr(&self) -> *const f32 {
        self.lorenz_lines.as_ptr()
    }

    pub fn get_lorenz_lines_count(&self) -> usize {
        self.lorenz_lines.len()
    }

    // --- Efecto Agujero Negro Relativista ---

    pub fn update_black_hole(&mut self, dt: f32) {
        self.black_hole.update(dt);
        self.black_hole_render.clear();

        let cx = self.width * 0.5;
        let cy = self.height * 0.5;

        // Inclinación del disco (proyección elíptica isométrica)
        let tilt_cos = 0.42;

        for i in 0..self.black_hole.count {
            let r = self.black_hole.particles_r[i];
            let theta = self.black_hole.particles_theta[i];
            let (sin_t, cos_t) = theta.sin_cos();

            let px = cx + r * cos_t;
            let py = cy + r * sin_t * tilt_cos;

            // Radiación Doppler beaming: partículas que se acercan son más brillantes y grandes
            let doppler = (cos_t * 0.4 + 1.0).clamp(0.4, 1.8);
            let radius = 1.6 * doppler;
            let col = self.black_hole.particles_color[i];

            self.black_hole_render.push(px);
            self.black_hole_render.push(py);
            self.black_hole_render.push(radius);
            self.black_hole_render.push(col as f32);
        }
    }

    pub fn get_black_hole_ptr(&self) -> *const f32 {
        self.black_hole_render.as_ptr()
    }

    pub fn get_black_hole_count(&self) -> usize {
        self.black_hole_render.len()
    }

    // --- Layout de Grafos de Aprendizaje con Barnes-Hut O(N log N) ---

    pub fn graph_clear(&mut self) {
        self.graph_layout.clear();
        self.graph_positions.clear();
    }

    pub fn graph_add_node(&mut self, x: f32, y: f32, mass: f32) -> usize {
        self.graph_layout.add_node(x, y, mass)
    }

    pub fn graph_add_edge(&mut self, u: usize, v: usize, rest_len: f32) {
        self.graph_layout.add_edge(u, v, rest_len);
    }

    pub fn graph_step(&mut self, dt: f32, repulsion_k: f32, spring_k: f32, damping: f32) {
        self.graph_layout.step(dt, repulsion_k, spring_k, damping);

        self.graph_positions.clear();
        for node in &self.graph_layout.nodes {
            self.graph_positions.push(node.x);
            self.graph_positions.push(node.y);
        }
    }

    pub fn graph_get_positions_ptr(&self) -> *const f32 {
        self.graph_positions.as_ptr()
    }

    pub fn graph_get_nodes_count(&self) -> usize {
        self.graph_layout.nodes.len()
    }

    // --- Efecto: Polígonos Cuánticos ---

    pub fn polygons_update(&mut self, dt: f32) {
        self.polygons.update(dt);
    }

    pub fn polygons_get_ptr(&self) -> *const f32 {
        self.polygons.render_buffer.as_ptr()
    }

    pub fn polygons_get_count(&self) -> usize {
        self.polygons.render_buffer.len()
    }

    // --- Efecto: Vórtice Dimensional ---

    pub fn vortex_update(&mut self, dt: f32) {
        self.vortex.update(dt);
    }

    pub fn vortex_get_lines_ptr(&self) -> *const f32 {
        self.vortex.lines_buffer.as_ptr()
    }

    pub fn vortex_get_lines_count(&self) -> usize {
        self.vortex.lines_buffer.len()
    }

    // --- Efecto: Matrix Cyber Rain ---

    pub fn matrix_update(&mut self, dt: f32) {
        self.matrix_rain.update(dt);
    }

    pub fn matrix_get_ptr(&self) -> *const f32 {
        self.matrix_rain.render_buffer.as_ptr()
    }

    pub fn matrix_get_count(&self) -> usize {
        self.matrix_rain.render_buffer.len()
    }

    // --- Actor y Drones Tácticos (ASCII Engine) ---

    pub fn actor_set_state(&mut self, state: u8) {
        let st = match state {
            1 => prig_ascii_engine::actor::ActorState::Eval,
            2 => prig_ascii_engine::actor::ActorState::Code,
            3 => prig_ascii_engine::actor::ActorState::Alert,
            _ => prig_ascii_engine::actor::ActorState::Idle,
        };
        self.character.set_state(st);
    }

    pub fn actor_update(&mut self, dt: f32, cursor_code_x: f32, cursor_code_y: f32) {
        self.character.update(dt, cursor_code_x, cursor_code_y);
    }

    pub fn actor_get_x(&self) -> f32 {
        self.character.spring_pos.x
    }

    pub fn actor_get_y(&self) -> f32 {
        self.character.spring_pos.y
    }

    pub fn actor_get_breath_offset(&self) -> f32 {
        self.character.get_breath_offset()
    }

    pub fn actor_is_blinking(&self) -> bool {
        self.character.is_blinking
    }

    pub fn actor_get_eye_dx(&self) -> f32 {
        self.character.eye_spring.x
    }

    pub fn actor_get_eye_dy(&self) -> f32 {
        self.character.eye_spring.y
    }

    pub fn drones_update(&mut self, dt: f32) {
        self.drones.update(dt);
        let cx = self.actor_get_x();
        let cy = self.actor_get_y() + self.actor_get_breath_offset();
        let states = self.drones.get_render_states(cx, cy);

        self.drone_render_buffer.clear();
        for state in &states {
            self.drone_render_buffer.push(state.x);
            self.drone_render_buffer.push(state.y);
            self.drone_render_buffer.push(state.scale);
            self.drone_render_buffer.push(state.alpha);
            self.drone_render_buffer.push(state.z_depth);
            self.drone_render_buffer.push(if state.is_behind { 1.0 } else { 0.0 });
            // Los bits exactos del color (JS los lee con una vista Uint32Array): como número, f32 solo tiene 24 bits
            // de mantisa y el byte bajo se redondeaba
            self.drone_render_buffer.push(f32::from_bits(state.color_rgba));
        }
    }

    pub fn drones_get_render_ptr(&self) -> *const f32 {
        self.drone_render_buffer.as_ptr()
    }

    pub fn drones_get_render_count(&self) -> usize {
        self.drone_render_buffer.len()
    }
}

