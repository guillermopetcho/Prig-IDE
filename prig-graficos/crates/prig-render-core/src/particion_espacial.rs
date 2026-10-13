//! Particionamiento espacial contiguo 1D para búsqueda de vecinos en O(N).
//! Utiliza una lista enlazada estática plana (head/next) que elimina al 100% las alocaciones por fotograma.

pub struct SpatialGrid1D {
    pub cell_size: f32,
    pub cols: usize,
    pub rows: usize,
    pub head: Vec<i32>,
    pub next: Vec<i32>,
    pub lines_buffer: Vec<f32>, // Búfer contiguo reutilizable [x1, y1, x2, y2, alpha, ...]
}

impl SpatialGrid1D {
    pub fn new(cell_size: f32, max_particles: usize, width: f32, height: f32) -> Self {
        let cols = (width / cell_size).ceil().max(1.0) as usize;
        let rows = (height / cell_size).ceil().max(1.0) as usize;
        let total_cells = cols * rows;

        Self {
            cell_size,
            cols,
            rows,
            head: vec![-1; total_cells],
            next: vec![-1; max_particles],
            lines_buffer: Vec::with_capacity(max_particles * 16),
        }
    }

    /// Redimensiona la cuadrícula si el tamaño de pantalla cambia.
    pub fn resize(&mut self, width: f32, height: f32, max_particles: usize) {
        let cols = (width / self.cell_size).ceil().max(1.0) as usize;
        let rows = (height / self.cell_size).ceil().max(1.0) as usize;
        let total_cells = cols * rows;

        // cols y rows siempre: con el mismo total de celdas y otra forma (10×6 → 6×10), antes quedaban los viejos y
        // las partículas caían en celdas equivocadas (faltaban conexiones)
        self.cols = cols;
        self.rows = rows;
        if self.head.len() != total_cells {
            self.head.resize(total_cells, -1);
        }
        if self.next.len() < max_particles {
            self.next.resize(max_particles, -1);
        }
    }

    /// Limpia e indexa todas las partículas en la cuadrícula contigua.
    #[inline(always)]
    pub fn index_particles(&mut self, px: &[f32], py: &[f32], count: usize) {
        self.head.fill(-1);
        if self.next.len() < count {
            self.next.resize(count, -1);
        }

        let inv_size = 1.0 / self.cell_size;
        let cols = self.cols;
        let rows = self.rows;

        for i in 0..count {
            let cx = ((px[i] * inv_size) as usize).min(cols - 1);
            let cy = ((py[i] * inv_size) as usize).min(rows - 1);
            let cell_idx = cy * cols + cx;

            self.next[i] = self.head[cell_idx];
            self.head[cell_idx] = i as i32;
        }
    }

    /// Genera las líneas de conexión entre partículas vecinas en O(N).
    /// Guarda en `lines_buffer` grupos de 5 floats: [x1, y1, x2, y2, alpha].
    pub fn find_connections(
        &mut self,
        px: &[f32],
        py: &[f32],
        count: usize,
        max_dist: f32,
        base_alpha: f32,
    ) {
        self.lines_buffer.clear();
        let max_dist_sq = max_dist * max_dist;
        let cols = self.cols;
        let rows = self.rows;
        let inv_size = 1.0 / self.cell_size;

        for i in 0..count {
            let cx = ((px[i] * inv_size) as isize).clamp(0, cols as isize - 1);
            let cy = ((py[i] * inv_size) as isize).clamp(0, rows as isize - 1);

            let xi = px[i];
            let yi = py[i];

            // Revisa las celdas adyacentes 3x3
            for dy in -1..=1 {
                let ny = cy + dy;
                if ny < 0 || ny >= rows as isize {
                    continue;
                }
                for dx in -1..=1 {
                    let nx = cx + dx;
                    if nx < 0 || nx >= cols as isize {
                        continue;
                    }

                    let cell_idx = (ny as usize) * cols + (nx as usize);
                    let mut curr = self.head[cell_idx];

                    while curr != -1 {
                        let j = curr as usize;
                        // Solo pares únicos j > i para no duplicar líneas
                        if j > i {
                            let ddx = xi - px[j];
                            let ddy = yi - py[j];
                            let dist_sq = ddx * ddx + ddy * ddy;

                            if dist_sq < max_dist_sq {
                                let dist = dist_sq.sqrt();
                                let alpha = (1.0 - (dist / max_dist)) * base_alpha;
                                self.lines_buffer.push(xi);
                                self.lines_buffer.push(yi);
                                self.lines_buffer.push(px[j]);
                                self.lines_buffer.push(py[j]);
                                self.lines_buffer.push(alpha);
                            }
                        }
                        curr = self.next[j];
                    }
                }
            }
        }
    }
}


#[cfg(test)]
mod pruebas_redimension {
    use super::SpatialGrid1D;

    /// Misma cantidad de celdas y otra forma: las columnas y filas tienen que cambiar igual
    #[test]
    fn redimensionar_con_el_mismo_total_de_celdas() {
        let mut g = SpatialGrid1D::new(10.0, 4, 100.0, 60.0); // 10 × 6
        assert_eq!((g.cols, g.rows), (10, 6));
        g.resize(60.0, 100.0, 4); // 6 × 10
        assert_eq!((g.cols, g.rows), (6, 10));
        // Dos partículas cercanas en la esquina inferior (ahora la grilla es alta): se conectan
        let (x, y) = (vec![55.0, 57.0], vec![95.0, 96.0]);
        g.index_particles(&x, &y, 2);
        g.find_connections(&x, &y, 2, 20.0, 1.0);
        assert_eq!(g.lines_buffer.len(), 5);
    }
}
