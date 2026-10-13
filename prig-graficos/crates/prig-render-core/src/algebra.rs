//! Álgebra lineal vectorial y matricial 2D, 3D y 4D hiperdimensional para Prig.

/// Vector bidimensional.
#[derive(Debug, Clone, Copy, PartialEq, Default)]
pub struct Vec2 {
    pub x: f32,
    pub y: f32,
}

impl Vec2 {
    #[inline(always)]
    pub const fn new(x: f32, y: f32) -> Self {
        Self { x, y }
    }

    #[inline(always)]
    pub fn length_squared(self) -> f32 {
        self.x * self.x + self.y * self.y
    }

    #[inline(always)]
    pub fn length(self) -> f32 {
        self.length_squared().sqrt()
    }

    #[inline(always)]
    pub fn distance(self, other: Self) -> f32 {
        (self - other).length()
    }

    #[inline(always)]
    pub fn normalize(self) -> Self {
        let len = self.length();
        if len > 1e-6 {
            Self {
                x: self.x / len,
                y: self.y / len,
            }
        } else {
            Self::new(0.0, 0.0)
        }
    }

    #[inline(always)]
    pub fn dot(self, other: Self) -> f32 {
        self.x * other.x + self.y * other.y
    }
}

impl core::ops::Add for Vec2 {
    type Output = Self;
    #[inline(always)]
    fn add(self, rhs: Self) -> Self {
        Self::new(self.x + rhs.x, self.y + rhs.y)
    }
}

impl core::ops::Sub for Vec2 {
    type Output = Self;
    #[inline(always)]
    fn sub(self, rhs: Self) -> Self {
        Self::new(self.x - rhs.x, self.y - rhs.y)
    }
}

impl core::ops::Mul<f32> for Vec2 {
    type Output = Self;
    #[inline(always)]
    fn mul(self, rhs: f32) -> Self {
        Self::new(self.x * rhs, self.y * rhs)
    }
}

/// Vector tridimensional.
#[derive(Debug, Clone, Copy, PartialEq, Default)]
pub struct Vec3 {
    pub x: f32,
    pub y: f32,
    pub z: f32,
}

impl Vec3 {
    #[inline(always)]
    pub const fn new(x: f32, y: f32, z: f32) -> Self {
        Self { x, y, z }
    }

    #[inline(always)]
    pub fn length_squared(self) -> f32 {
        self.x * self.x + self.y * self.y + self.z * self.z
    }

    #[inline(always)]
    pub fn length(self) -> f32 {
        self.length_squared().sqrt()
    }

    #[inline(always)]
    pub fn normalize(self) -> Self {
        let len = self.length();
        if len > 1e-6 {
            Self {
                x: self.x / len,
                y: self.y / len,
                z: self.z / len,
            }
        } else {
            Self::new(0.0, 0.0, 0.0)
        }
    }

    #[inline(always)]
    pub fn cross(self, other: Self) -> Self {
        Self {
            x: self.y * other.z - self.z * other.y,
            y: self.z * other.x - self.x * other.z,
            z: self.x * other.y - self.y * other.x,
        }
    }
}

impl core::ops::Add for Vec3 {
    type Output = Self;
    #[inline(always)]
    fn add(self, rhs: Self) -> Self {
        Self::new(self.x + rhs.x, self.y + rhs.y, self.z + rhs.z)
    }
}

impl core::ops::Sub for Vec3 {
    type Output = Self;
    #[inline(always)]
    fn sub(self, rhs: Self) -> Self {
        Self::new(self.x - rhs.x, self.y - rhs.y, self.z - rhs.z)
    }
}

impl core::ops::Mul<f32> for Vec3 {
    type Output = Self;
    #[inline(always)]
    fn mul(self, rhs: f32) -> Self {
        Self::new(self.x * rhs, self.y * rhs, self.z * rhs)
    }
}

/// Vector tetradimensional (4D) para coordenadas hiperdimensionales (Tesseract).
#[derive(Debug, Clone, Copy, PartialEq, Default)]
pub struct Vec4 {
    pub x: f32,
    pub y: f32,
    pub z: f32,
    pub w: f32,
}

impl Vec4 {
    #[inline(always)]
    pub const fn new(x: f32, y: f32, z: f32, w: f32) -> Self {
        Self { x, y, z, w }
    }

    #[inline(always)]
    pub fn rotate_xy(self, theta: f32) -> Self {
        let (sin, cos) = theta.sin_cos();
        Self {
            x: self.x * cos - self.y * sin,
            y: self.x * sin + self.y * cos,
            z: self.z,
            w: self.w,
        }
    }

    #[inline(always)]
    pub fn rotate_xz(self, theta: f32) -> Self {
        let (sin, cos) = theta.sin_cos();
        Self {
            x: self.x * cos - self.z * sin,
            y: self.y,
            z: self.x * sin + self.z * cos,
            w: self.w,
        }
    }

    #[inline(always)]
    pub fn rotate_xw(self, theta: f32) -> Self {
        let (sin, cos) = theta.sin_cos();
        Self {
            x: self.x * cos - self.w * sin,
            y: self.y,
            z: self.z,
            w: self.x * sin + self.w * cos,
        }
    }

    #[inline(always)]
    pub fn rotate_yz(self, theta: f32) -> Self {
        let (sin, cos) = theta.sin_cos();
        Self {
            x: self.x,
            y: self.y * cos - self.z * sin,
            z: self.y * sin + self.z * cos,
            w: self.w,
        }
    }

    #[inline(always)]
    pub fn rotate_yw(self, theta: f32) -> Self {
        let (sin, cos) = theta.sin_cos();
        Self {
            x: self.x,
            y: self.y * cos - self.w * sin,
            z: self.z,
            w: self.y * sin + self.w * cos,
        }
    }

    #[inline(always)]
    pub fn rotate_zw(self, theta: f32) -> Self {
        let (sin, cos) = theta.sin_cos();
        Self {
            x: self.x,
            y: self.y,
            z: self.z * cos - self.w * sin,
            w: self.z * sin + self.w * cos,
        }
    }

    /// Proyección estereográfica 4D -> 3D con distancia de cámara 4D `dist_w`.
    #[inline(always)]
    pub fn project_to_3d(self, dist_w: f32) -> Vec3 {
        let factor = 1.0 / (dist_w - self.w).max(0.1);
        Vec3::new(self.x * factor, self.y * factor, self.z * factor)
    }
}

/// Proyección 3D a pantalla 2D con centro de viewport (cx, cy) y escala.
#[inline(always)]
pub fn project_3d_to_screen(p: Vec3, fov: f32, cx: f32, cy: f32, scale: f32) -> (Vec2, f32) {
    let z_depth = (p.z + fov).max(0.1);
    let scale_factor = (fov / z_depth) * scale;
    let screen = Vec2::new(cx + p.x * scale_factor, cy + p.y * scale_factor);
    (screen, scale_factor)
}
