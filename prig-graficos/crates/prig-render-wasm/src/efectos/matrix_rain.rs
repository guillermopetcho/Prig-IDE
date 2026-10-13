//! Simulación de la lluvia digital Matrix cyberpunk.

use prig_render_core::particulas::SimpleRng;

#[derive(Debug, Clone)]
pub struct MatrixRainSystem {
    pub col_width: f32,
    pub cols: usize,
    pub x: Vec<f32>,
    pub y: Vec<f32>,
    pub speed: Vec<f32>,
    pub length: Vec<f32>,
    pub width: f32,
    pub height: f32,
    pub render_buffer: Vec<f32>, // [col_x, head_y, length, speed, ...]
}

impl MatrixRainSystem {
    pub fn new(col_width: f32, width: f32, height: f32, seed: u64) -> Self {
        let cols = ((width / col_width).ceil().max(1.0) as usize) + 1;
        let mut rng = SimpleRng::new(seed);

        let mut x = Vec::with_capacity(cols);
        let mut y = Vec::with_capacity(cols);
        let mut speed = Vec::with_capacity(cols);
        let mut length = Vec::with_capacity(cols);

        for i in 0..cols {
            x.push((i as f32) * col_width);
            y.push(rng.range_f32(-height, 0.0));
            speed.push(rng.range_f32(160.0, 360.0));
            length.push(rng.range_f32(8.0, 24.0));
        }

        Self {
            col_width,
            cols,
            x,
            y,
            speed,
            length,
            width,
            height,
            render_buffer: Vec::with_capacity(cols * 4),
        }
    }

    pub fn resize(&mut self, width: f32, height: f32) {
        self.width = width;
        self.height = height;
        let cols = ((width / self.col_width).ceil().max(1.0) as usize) + 1;
        if cols > self.cols {
            let mut rng = SimpleRng::new(42);
            for i in self.cols..cols {
                self.x.push((i as f32) * self.col_width);
                self.y.push(rng.range_f32(-height, 0.0));
                self.speed.push(rng.range_f32(160.0, 360.0));
                self.length.push(rng.range_f32(8.0, 24.0));
            }
            self.cols = cols;
        }
    }

    pub fn update(&mut self, dt: f32) {
        let dt = dt.clamp(0.001, 0.05);
        let h = self.height;
        self.render_buffer.clear();

        for i in 0..self.cols {
            self.y[i] += self.speed[i] * dt;
            let total_len = self.length[i] * 16.0;

            if self.y[i] - total_len > h {
                self.y[i] = -total_len;
            }

            self.render_buffer.push(self.x[i]);
            self.render_buffer.push(self.y[i]);
            self.render_buffer.push(self.length[i]);
            self.render_buffer.push(self.speed[i]);
        }
    }
}

