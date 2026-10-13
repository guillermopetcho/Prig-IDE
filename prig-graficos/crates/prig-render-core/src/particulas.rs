//! Sistema de partículas optimizado con modelo Structure of Arrays (SoA).
//! Proporciona acceso a memoria lineal contigua para procesamiento SIMD y cero pausas de GC.

#[derive(Debug, Clone, Default)]
pub struct ParticleSystem {
    pub count: usize,
    pub x: Vec<f32>,
    pub y: Vec<f32>,
    pub vx: Vec<f32>,
    pub vy: Vec<f32>,
    pub radius: Vec<f32>,
    pub base_radius: Vec<f32>,
    pub color_rgba: Vec<u32>,
    pub alpha: Vec<f32>,
    pub width: f32,
    pub height: f32,
}

/// Generador de números pseudoaleatorios simple (Xorshift64) para inicialización sin crates externos.
#[derive(Debug, Clone)]
pub struct SimpleRng {
    state: u64,
}

impl SimpleRng {
    pub const fn new(seed: u64) -> Self {
        Self {
            state: if seed == 0 { 0x8543_2910_f21a_63c1 } else { seed },
        }
    }

    #[inline(always)]
    pub fn next_u32(&mut self) -> u32 {
        self.state ^= self.state << 13;
        self.state ^= self.state >> 7;
        self.state ^= self.state << 17;
        (self.state & 0xFFFF_FFFF) as u32
    }

    #[inline(always)]
    pub fn next_f32(&mut self) -> f32 {
        (self.next_u32() as f32) / (u32::MAX as f32)
    }

    #[inline(always)]
    pub fn range_f32(&mut self, min: f32, max: f32) -> f32 {
        min + self.next_f32() * (max - min)
    }
}

impl ParticleSystem {
    /// Inicializa un sistema de `count` partículas distribuido uniformemente en [0, width] x [0, height].
    pub fn new(count: usize, width: f32, height: f32, seed: u64) -> Self {
        let mut rng = SimpleRng::new(seed);
        let mut sys = Self {
            count,
            x: Vec::with_capacity(count),
            y: Vec::with_capacity(count),
            vx: Vec::with_capacity(count),
            vy: Vec::with_capacity(count),
            radius: Vec::with_capacity(count),
            base_radius: Vec::with_capacity(count),
            color_rgba: Vec::with_capacity(count),
            alpha: Vec::with_capacity(count),
            width: width.max(1.0),
            height: height.max(1.0),
        };

        // Paleta ciberpunk / técnica por defecto: cian neón, azul profundo, verde terminal
        let colores = [
            0x00F0FF_FF, // Cian neón #00f0ff
            0x89B4FA_FF, // Azul hielo #89b4fa
            0xA6E3A1_FF, // Verde terminal #a6e3a1
            0xCBA6F7_FF, // Púrpura eléctrico #cba6f7
        ];

        for i in 0..count {
            sys.x.push(rng.range_f32(0.0, sys.width));
            sys.y.push(rng.range_f32(0.0, sys.height));
            // Velocidades moderadas en px/s
            sys.vx.push(rng.range_f32(-35.0, 35.0));
            sys.vy.push(rng.range_f32(-35.0, 35.0));
            let r = rng.range_f32(1.2, 2.6);
            sys.radius.push(r);
            sys.base_radius.push(r);
            sys.color_rgba.push(colores[i % colores.len()]);
            sys.alpha.push(rng.range_f32(0.35, 0.95));
        }

        sys
    }

    /// Actualiza la posición y cinemática de las partículas para un paso de tiempo `dt` (segundos).
    pub fn update(&mut self, dt: f32, mouse_x: f32, mouse_y: f32, mouse_active: bool) {
        let dt_clamped = dt.clamp(0.001, 0.05); // previene túneles por caídas de FPS
        let w = self.width;
        let h = self.height;

        let mouse_influence_radius_sq = 120.0 * 120.0;

        for i in 0..self.count {
            // Interacción táctica con el cursor (repulsión suave)
            if mouse_active {
                let dx = self.x[i] - mouse_x;
                let dy = self.y[i] - mouse_y;
                let dist_sq = dx * dx + dy * dy;
                if dist_sq < mouse_influence_radius_sq && dist_sq > 1.0 {
                    let dist = dist_sq.sqrt();
                    let force = (1.0 - dist / 120.0) * 85.0;
                    self.x[i] += (dx / dist) * force * dt_clamped;
                    self.y[i] += (dy / dist) * force * dt_clamped;
                }
            }

            // Integración de Euler simple en SoA
            self.x[i] += self.vx[i] * dt_clamped;
            self.y[i] += self.vy[i] * dt_clamped;

            // Envoltura toroidal suave en bordes (wrapping)
            if self.x[i] < -10.0 {
                self.x[i] = w + 10.0;
            } else if self.x[i] > w + 10.0 {
                self.x[i] = -10.0;
            }

            if self.y[i] < -10.0 {
                self.y[i] = h + 10.0;
            } else if self.y[i] > h + 10.0 {
                self.y[i] = -10.0;
            }
        }
    }

    /// Redimensiona el espacio de simulación.
    pub fn resize(&mut self, width: f32, height: f32) {
        self.width = width.max(1.0);
        self.height = height.max(1.0);
    }
}

