//! Máquina de estados cinemática y física analítica para el personaje ASCII.

use prig_render_core::spring_physics::Spring2D;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ActorState {
    Idle,
    Eval,
    Code,
    Alert,
}

#[derive(Debug, Clone)]
pub struct CharacterActor {
    pub state: ActorState,
    pub spring_pos: Spring2D,
    pub eye_spring: Spring2D,
    pub breath_phase: f32,
    pub blink_timer: f32,
    pub is_blinking: bool,
    pub shield_energy: f32,
    pub viewport_w: f32,
    pub viewport_h: f32,
    pub target_ratio_x: f32,
    pub target_ratio_y: f32,
}

impl CharacterActor {
    pub fn new(viewport_w: f32, viewport_h: f32) -> Self {
        let x = viewport_w * 0.88;
        let y = viewport_h * 0.88;

        Self {
            state: ActorState::Idle,
            spring_pos: Spring2D::new(x, y, 4.5, 0.85),
            eye_spring: Spring2D::new(0.0, 0.0, 6.0, 0.9),
            breath_phase: 0.0,
            blink_timer: 3.5,
            is_blinking: false,
            shield_energy: 1.0,
            viewport_w,
            viewport_h,
            target_ratio_x: 0.88,
            target_ratio_y: 0.88,
        }
    }

    pub fn set_state(&mut self, state: ActorState) {
        self.state = state;
    }

    pub fn resize(&mut self, w: f32, h: f32) {
        self.viewport_w = w.max(1.0);
        self.viewport_h = h.max(1.0);
        let tx = self.viewport_w * self.target_ratio_x;
        let ty = self.viewport_h * self.target_ratio_y;
        self.spring_pos.set_target(tx, ty);
    }

    /// Actualiza la posición con resortes, parpadeo estocástico y seguimiento ocular.
    pub fn update(&mut self, dt: f32, cursor_code_x: f32, cursor_code_y: f32) {
        let dt_clamped = dt.clamp(0.001, 0.05);

        // 1. Cinemática de posición base
        let tx = self.viewport_w * self.target_ratio_x;
        let ty = self.viewport_h * self.target_ratio_y;
        self.spring_pos.set_target(tx, ty);
        self.spring_pos.update(dt_clamped);

        // 2. Respiración sutil
        self.breath_phase += dt_clamped * 1.8;
        if self.breath_phase > std::f32::consts::TAU {
            self.breath_phase -= std::f32::consts::TAU;
        }

        // 3. Temporizador de parpadeo biológico
        self.blink_timer -= dt_clamped;
        if self.blink_timer <= 0.0 {
            self.is_blinking = true;
            if self.blink_timer <= -0.15 {
                self.is_blinking = false;
                self.blink_timer = 2.8 + (self.breath_phase.sin().abs() * 2.5);
            }
        }

        // 4. Seguimiento ocular hacia el código en edición
        let char_x = self.spring_pos.x;
        let char_y = self.spring_pos.y;
        let look_dx = (cursor_code_x - char_x).clamp(-80.0, 80.0) * 0.08;
        let look_dy = (cursor_code_y - char_y).clamp(-80.0, 80.0) * 0.08;
        self.eye_spring.set_target(look_dx, look_dy);
        self.eye_spring.update(dt_clamped);
    }

    /// Obtiene el desplazamiento vertical por respiración (en píxeles).
    #[inline(always)]
    pub fn get_breath_offset(&self) -> f32 {
        self.breath_phase.sin() * 2.2
    }
}

