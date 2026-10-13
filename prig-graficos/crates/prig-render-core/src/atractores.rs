//! Integrador numérico Runge-Kutta de 4to orden (RK4) y atractores caóticos.

use crate::algebra::Vec3;

/// Paso de integración numérica Runge-Kutta 4 (RK4).
#[inline(always)]
pub fn rk4_step<F>(p: Vec3, dt: f32, deriv: F) -> Vec3
where
    F: Fn(Vec3) -> Vec3,
{
    let k1 = deriv(p);
    let k2 = deriv(p + k1 * (0.5 * dt));
    let k3 = deriv(p + k2 * (0.5 * dt));
    let k4 = deriv(p + k3 * dt);

    p + (k1 + k2 * 2.0 + k3 * 2.0 + k4) * (dt / 6.0)
}

/// Atractor caótico de Lorentz.
/// Parámetros estándar: sigma = 10.0, rho = 28.0, beta = 8.0 / 3.0.
#[derive(Debug, Clone)]
pub struct LorenzAttractor {
    pub sigma: f32,
    pub rho: f32,
    pub beta: f32,
    pub position: Vec3,
    pub trail: Vec<Vec3>,
    pub max_trail_len: usize,
}

impl LorenzAttractor {
    pub fn new(initial_pos: Vec3, max_trail_len: usize) -> Self {
        Self {
            sigma: 10.0,
            rho: 28.0,
            beta: 8.0 / 3.0,
            position: initial_pos,
            trail: Vec::with_capacity(max_trail_len),
            max_trail_len,
        }
    }

    #[inline(always)]
    fn deriv(&self, p: Vec3) -> Vec3 {
        Vec3::new(
            self.sigma * (p.y - p.x),
            p.x * (self.rho - p.z) - p.y,
            p.x * p.y - self.beta * p.z,
        )
    }

    pub fn step(&mut self, dt: f32) {
        let next_pos = rk4_step(self.position, dt, |p| self.deriv(p));
        self.position = next_pos;

        if self.trail.len() >= self.max_trail_len {
            self.trail.remove(0);
        }
        self.trail.push(next_pos);
    }
}

/// Atractor caótico de Rössler.
/// Parámetros estándar: a = 0.2, b = 0.2, c = 5.7.
#[derive(Debug, Clone)]
pub struct RosslerAttractor {
    pub a: f32,
    pub b: f32,
    pub c: f32,
    pub position: Vec3,
    pub trail: Vec<Vec3>,
    pub max_trail_len: usize,
}

impl RosslerAttractor {
    pub fn new(initial_pos: Vec3, max_trail_len: usize) -> Self {
        Self {
            a: 0.2,
            b: 0.2,
            c: 5.7,
            position: initial_pos,
            trail: Vec::with_capacity(max_trail_len),
            max_trail_len,
        }
    }

    #[inline(always)]
    fn deriv(&self, p: Vec3) -> Vec3 {
        Vec3::new(
            -p.y - p.z,
            p.x + self.a * p.y,
            self.b + p.z * (p.x - self.c),
        )
    }

    pub fn step(&mut self, dt: f32) {
        let next_pos = rk4_step(self.position, dt, |p| self.deriv(p));
        self.position = next_pos;

        if self.trail.len() >= self.max_trail_len {
            self.trail.remove(0);
        }
        self.trail.push(next_pos);
    }
}

/// Disco de acreción de agujero negro relativista (aproximación Schwarzschild).
#[derive(Debug, Clone)]
pub struct BlackHoleSystem {
    pub particles_r: Vec<f32>,
    pub particles_theta: Vec<f32>,
    pub particles_speed: Vec<f32>,
    pub particles_color: Vec<u32>,
    pub count: usize,
    pub rs: f32, // Radio de Schwarzschild (horizonte de sucesos)
    pub isco: f32, // Órbita circular estable más interna (3 * rs)
}

impl BlackHoleSystem {
    pub fn new(count: usize, rs: f32) -> Self {
        let mut r = Vec::with_capacity(count);
        let mut theta = Vec::with_capacity(count);
        let mut speed = Vec::with_capacity(count);
        let mut color = Vec::with_capacity(count);

        let isco = rs * 3.0;

        for i in 0..count {
            let frac = (i as f32) / (count as f32);
            let radius = isco + frac * 240.0;
            r.push(radius);
            theta.push(frac * std::f32::consts::TAU * 3.0);
            // Velocidad kepleriana relativista v ~ sqrt(GM / r)
            let v = (1200.0 / radius.sqrt()).clamp(0.2, 4.5);
            speed.push(v);

            // Gradiente térmico: interior blanco/cian supercaliente, exterior naranja/azul
            let col = if frac < 0.2 {
                0xFFFFFF_FF // Blanco plasma
            } else if frac < 0.5 {
                0x00F0FF_FF // Cian neón
            } else {
                0x89B4FA_FF // Azul gravitatorio
            };
            color.push(col);
        }

        Self {
            particles_r: r,
            particles_theta: theta,
            particles_speed: speed,
            particles_color: color,
            count,
            rs,
            isco,
        }
    }

    pub fn update(&mut self, dt: f32) {
        for i in 0..self.count {
            self.particles_theta[i] += self.particles_speed[i] * dt;
            if self.particles_theta[i] > std::f32::consts::TAU {
                self.particles_theta[i] -= std::f32::consts::TAU;
            }
        }
    }
}

