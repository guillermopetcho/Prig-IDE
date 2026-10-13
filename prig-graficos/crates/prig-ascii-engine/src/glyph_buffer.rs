//! Búfer contiguo de glifos ASCII para rasterización de alta velocidad.

#[derive(Debug, Clone, Copy)]
pub struct Glyph {
    pub col: u16,
    pub row: u16,
    pub ch: char,
    pub color_rgba: u32,
    pub alpha: f32,
}

pub struct GlyphBuffer {
    pub glyphs: Vec<Glyph>,
    pub max_cols: u16,
    pub max_rows: u16,
}

impl GlyphBuffer {
    pub fn new(max_cols: u16, max_rows: u16) -> Self {
        let capacity = (max_cols as usize) * (max_rows as usize);
        Self {
            glyphs: Vec::with_capacity(capacity),
            max_cols,
            max_rows,
        }
    }

    #[inline(always)]
    pub fn clear(&mut self) {
        self.glyphs.clear();
    }

    pub fn write_str(&mut self, start_col: u16, row: u16, text: &str, color_rgba: u32, alpha: f32) {
        if row >= self.max_rows {
            return;
        }

        let mut c = start_col;
        for ch in text.chars() {
            if c >= self.max_cols {
                break;
            }
            if ch != ' ' {
                self.glyphs.push(Glyph {
                    col: c,
                    row,
                    ch,
                    color_rgba,
                    alpha,
                });
            }
            c += 1;
        }
    }
}

