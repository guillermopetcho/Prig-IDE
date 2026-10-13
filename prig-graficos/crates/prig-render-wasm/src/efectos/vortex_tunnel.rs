//! Simulación matemática del túnel de vórtice dimensional.

#[derive(Debug, Clone)]
pub struct VortexTunnelSystem {
    pub rotation: f32,
    pub speed: f32,
    pub width: f32,
    pub height: f32,
    pub lines_buffer: Vec<f32>, // [x1, y1, x2, y2, alpha, ...]
}

impl VortexTunnelSystem {
    pub fn new(width: f32, height: f32) -> Self {
        Self {
            rotation: 0.0,
            speed: 0.85,
            width: width.max(1.0),
            height: height.max(1.0),
            lines_buffer: Vec::with_capacity(36 * 16 * 5),
        }
    }

    pub fn resize(&mut self, width: f32, height: f32) {
        self.width = width.max(1.0);
        self.height = height.max(1.0);
    }

    pub fn update(&mut self, dt: f32) {
        self.rotation += self.speed * dt;
        if self.rotation > std::f32::consts::TAU {
            self.rotation -= std::f32::consts::TAU;
        }

        self.lines_buffer.clear();

        let cx = self.width * 0.5;
        let cy = self.height * 0.5;
        let max_r = (cx * cx + cy * cy).sqrt();

        // 1. Rayos radiales hipnóticos
        let num_spokes = 8;
        let spoke_step = std::f32::consts::TAU / (num_spokes as f32);

        let mut r = 25.0;
        while r < max_r {
            let frac = r / max_r;
            let alpha = (0.28 - frac * 0.22).clamp(0.04, 0.35);

            for s in 0..num_spokes {
                let a = self.rotation + (s as f32) * spoke_step + frac * 1.5; // espiral logarítmica
                let x1 = cx + a.cos() * (r - 14.0);
                let y1 = cy + a.sin() * (r - 14.0);
                let x2 = cx + a.cos() * r;
                let y2 = cy + a.sin() * r;

                self.lines_buffer.push(x1);
                self.lines_buffer.push(y1);
                self.lines_buffer.push(x2);
                self.lines_buffer.push(y2);
                self.lines_buffer.push(alpha);
            }

            r += 32.0;
        }
    }
}

