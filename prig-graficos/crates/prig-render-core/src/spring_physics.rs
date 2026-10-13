//! Física de resortes de segundo orden analítica para animación procedimental fluida.

#[derive(Debug, Clone, Copy)]
pub struct Spring2D {
    pub x: f32,
    pub y: f32,
    pub vx: f32,
    pub vy: f32,
    pub target_x: f32,
    pub target_y: f32,
    pub frequency: f32, // Frecuencia natural en Hz (ej. 3.0 a 6.0)
    pub damping: f32,   // Ratio de amortiguamiento zeta (1.0 = amortiguamiento crítico, suave)
}

impl Spring2D {
    pub fn new(x: f32, y: f32, frequency: f32, damping: f32) -> Self {
        Self {
            x,
            y,
            vx: 0.0,
            vy: 0.0,
            target_x: x,
            target_y: y,
            frequency,
            damping,
        }
    }

    pub fn set_target(&mut self, tx: f32, ty: f32) {
        self.target_x = tx;
        self.target_y = ty;
    }

    /// Actualiza el resorte analíticamente o por aproximación semi-implícita rápida y estable.
    pub fn update(&mut self, dt: f32) {
        let dt = dt.clamp(0.001, 0.05);
        let f = self.frequency * std::f32::consts::TAU; // omega_n
        let z = self.damping;

        // F = -k*x - c*v => a = -f^2 * (x - target) - 2*z*f*v
        let ax = -f * f * (self.x - self.target_x) - 2.0 * z * f * self.vx;
        let ay = -f * f * (self.y - self.target_y) - 2.0 * z * f * self.vy;

        self.vx += ax * dt;
        self.vy += ay * dt;

        self.x += self.vx * dt;
        self.y += self.vy * dt;
    }
}

