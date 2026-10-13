//! Cinemática orbital 3D de los tres drones tácticos del personaje.

#[derive(Debug, Clone)]
pub struct TacticalDrone {
    pub label: &'static str,
    pub radius_x: f32,
    pub radius_y: f32,
    pub speed: f32,
    pub phase: f32,
    pub tilt: f32,
    pub color_rgba: u32,
}

#[derive(Debug, Clone, Copy)]
pub struct DroneRenderState {
    pub x: f32,
    pub y: f32,
    pub scale: f32,
    pub alpha: f32,
    pub z_depth: f32,
    pub is_behind: bool,
    pub color_rgba: u32,
}

pub struct DroneFleet {
    pub drones: [TacticalDrone; 3],
}

impl DroneFleet {
    pub fn new() -> Self {
        Self {
            drones: [
                TacticalDrone {
                    label: "ALPHA",
                    radius_x: 52.0,
                    radius_y: 18.0,
                    speed: 1.6,
                    phase: 0.0,
                    tilt: 0.25,
                    color_rgba: 0x00F0FF_FF, // Neón cian
                },
                TacticalDrone {
                    label: "BETA",
                    radius_x: 68.0,
                    radius_y: 24.0,
                    speed: -1.2,
                    phase: 2.094, // 120 grados
                    tilt: -0.30,
                    color_rgba: 0xA6E3A1_FF, // Verde terminal
                },
                TacticalDrone {
                    label: "GAMMA",
                    radius_x: 82.0,
                    radius_y: 28.0,
                    speed: 0.9,
                    phase: 4.188, // 240 grados
                    tilt: 0.15,
                    color_rgba: 0xCBA6F7_FF, // Púrpura eléctrico
                },
            ],
        }
    }

    pub fn update(&mut self, dt: f32) {
        for drone in &mut self.drones {
            drone.phase += drone.speed * dt;
            if drone.phase > std::f32::consts::TAU {
                drone.phase -= std::f32::consts::TAU;
            } else if drone.phase < -std::f32::consts::TAU {
                drone.phase += std::f32::consts::TAU;
            }
        }
    }

    /// Retorna los estados proyectados en 2D alrededor del centro del personaje (cx, cy).
    pub fn get_render_states(&self, cx: f32, cy: f32) -> [DroneRenderState; 3] {
        let mut states = [DroneRenderState {
            x: 0.0,
            y: 0.0,
            scale: 1.0,
            alpha: 1.0,
            z_depth: 0.0,
            is_behind: false,
            color_rgba: 0,
        }; 3];

        for (i, drone) in self.drones.iter().enumerate() {
            let (sin_p, cos_p) = drone.phase.sin_cos();

            // Órbita elíptica inclinada en 3D
            let x3 = drone.radius_x * cos_p;
            let y3 = drone.radius_y * sin_p;
            let z3 = drone.radius_x * sin_p * 0.7; // Profundidad Z

            let px = cx + x3;
            let py = cy + y3 + x3 * drone.tilt;

            // Escala y profundidad
            let z_normalized = (z3 / drone.radius_x).clamp(-1.0, 1.0);
            let scale = 1.0 + z_normalized * 0.25;
            let alpha = 0.65 + z_normalized * 0.35;
            let is_behind = z3 < 0.0;

            states[i] = DroneRenderState {
                x: px,
                y: py,
                scale,
                alpha,
                z_depth: z3,
                is_behind,
                color_rgba: drone.color_rgba,
            };
        }

        states
    }
}

