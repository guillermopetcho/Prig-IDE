//! Prig ASCII Engine — Simulación y telemetría táctica de personajes y drones.

pub mod actor;
pub mod drones;
pub mod glyph_buffer;

pub use actor::{ActorState, CharacterActor};
pub use drones::{DroneFleet, DroneRenderState, TacticalDrone};
pub use glyph_buffer::{Glyph, GlyphBuffer};

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_character_actor_kinematics() {
        let mut actor = CharacterActor::new(1920.0, 1080.0);
        actor.update(0.016, 400.0, 300.0);
        assert!(actor.spring_pos.x > 1000.0);
        assert!(actor.get_breath_offset().abs() < 5.0);
    }

    #[test]
    fn test_drone_fleet_orbits() {
        let mut fleet = DroneFleet::new();
        fleet.update(0.1);
        let states = fleet.get_render_states(500.0, 500.0);
        assert_eq!(states.len(), 3);
        assert!((states[0].x - 500.0).abs() > 10.0);
    }

    #[test]
    fn test_glyph_buffer_writing() {
        let mut buffer = GlyphBuffer::new(80, 25);
        buffer.write_str(0, 0, "PRIG TACTICAL HUD", 0x00F0FF_FF, 1.0);
        assert_eq!(buffer.glyphs.len(), 15); // sin contar espacios
    }
}
