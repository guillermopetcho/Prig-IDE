//! Simulación física de polígonos cuánticos en memoria contigua.

use prig_render_core::particulas::SimpleRng;

#[derive(Debug, Clone)]
pub struct QuantumPolygonSystem {
    pub x: Vec<f32>,
    pub y: Vec<f32>,
    pub vx: Vec<f32>,
    pub vy: Vec<f32>,
    pub sides: Vec<usize>,
    pub radius: Vec<f32>,
    pub angle: Vec<f32>,
    pub v_angle: Vec<f32>,
    pub color_rgba: Vec<u32>,
    pub count: usize,
    pub width: f32,
    pub height: f32,
    pub render_buffer: Vec<f32>, // [x1, y1, x2, y2, color_u32, ...]
}

impl QuantumPolygonSystem {
    pub fn new(count: usize, width: f32, height: f32, seed: u64) -> Self {
        let mut rng = SimpleRng::new(seed);
        let mut sys = Self {
            x: Vec::with_capacity(count),
            y: Vec::with_capacity(count),
            vx: Vec::with_capacity(count),
            vy: Vec::with_capacity(count),
            sides: Vec::with_capacity(count),
            radius: Vec::with_capacity(count),
            angle: Vec::with_capacity(count),
            v_angle: Vec::with_capacity(count),
            color_rgba: Vec::with_capacity(count),
            count,
            width: width.max(1.0),
            height: height.max(1.0),
            render_buffer: Vec::with_capacity(count * 6 * 5),
        };

        let colores = [0x89B4FA_FF, 0xCBA6F7_FF, 0xA6E3A1_FF, 0x00F0FF_FF];

        for i in 0..count {
            sys.x.push(rng.range_f32(0.0, sys.width));
            sys.y.push(rng.range_f32(0.0, sys.height));
            sys.vx.push(rng.range_f32(-28.0, 28.0));
            sys.vy.push(rng.range_f32(-28.0, 28.0));
            sys.sides.push(3 + (rng.next_u32() % 4) as usize); // 3 a 6 lados
            sys.radius.push(rng.range_f32(18.0, 48.0));
            sys.angle.push(rng.range_f32(0.0, std::f32::consts::TAU));
            sys.v_angle.push(rng.range_f32(-1.2, 1.2));
            sys.color_rgba.push(colores[i % colores.len()]);
        }

        sys
    }

    pub fn resize(&mut self, width: f32, height: f32) {
        self.width = width.max(1.0);
        self.height = height.max(1.0);
    }

    pub fn update(&mut self, dt: f32) {
        let dt = dt.clamp(0.001, 0.05);
        let w = self.width;
        let h = self.height;

        self.render_buffer.clear();

        for i in 0..self.count {
            self.x[i] += self.vx[i] * dt;
            self.y[i] += self.vy[i] * dt;
            self.angle[i] += self.v_angle[i] * dt;

            let r = self.radius[i];
            if self.x[i] < -r {
                self.x[i] = w + r;
            } else if self.x[i] > w + r {
                self.x[i] = -r;
            }

            if self.y[i] < -r {
                self.y[i] = h + r;
            } else if self.y[i] > h + r {
                self.y[i] = -r;
            }

            // Generar vértices y aristas para trazado agrupado
            let cx = self.x[i];
            let cy = self.y[i];
            let sides = self.sides[i];
            let step = std::f32::consts::TAU / (sides as f32);
            let rot = self.angle[i];
            let col = self.color_rgba[i] as f32;

            for j in 0..sides {
                let a1 = rot + (j as f32) * step;
                let a2 = rot + ((j + 1) as f32) * step;

                let x1 = cx + a1.cos() * r;
                let y1 = cy + a1.sin() * r;
                let x2 = cx + a2.cos() * r;
                let y2 = cy + a2.sin() * r;

                self.render_buffer.push(x1);
                self.render_buffer.push(y1);
                self.render_buffer.push(x2);
                self.render_buffer.push(y2);
                self.render_buffer.push(col);
            }
        }
    }
}

