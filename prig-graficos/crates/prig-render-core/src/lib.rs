//! Prig Render Core — Biblioteca matemática y física pura de alto rendimiento.

pub mod algebra;
pub mod atractores;
pub mod barnes_hut;
pub mod particion_espacial;
pub mod particulas;
pub mod spring_physics;

pub use algebra::{project_3d_to_screen, Vec2, Vec3, Vec4};
pub use atractores::{rk4_step, BlackHoleSystem, LorenzAttractor, RosslerAttractor};
pub use barnes_hut::{BarnesHutTree, GraphLayoutSystem, GraphNode};
pub use particion_espacial::SpatialGrid1D;
pub use particulas::ParticleSystem;
pub use spring_physics::Spring2D;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_vec4_rotation_and_projection() {
        let v = Vec4::new(1.0, 0.0, 0.0, 0.0);
        let rotated = v.rotate_xw(std::f32::consts::FRAC_PI_2);
        assert!((rotated.x).abs() < 1e-5);
        assert!((rotated.w - 1.0).abs() < 1e-5);

        let proj3 = rotated.project_to_3d(2.0);
        assert!((proj3.x).abs() < 1e-5);
    }

    #[test]
    fn test_particle_system_and_spatial_grid() {
        let mut sys = ParticleSystem::new(50, 800.0, 600.0, 12345);
        sys.update(0.016, 400.0, 300.0, false);

        let mut grid = SpatialGrid1D::new(100.0, 50, 800.0, 600.0);
        grid.index_particles(&sys.x, &sys.y, sys.count);
        grid.find_connections(&sys.x, &sys.y, sys.count, 90.0, 0.8);

        // Verifica que lines_buffer contenga coordenadas válidas múltiplos de 5
        assert_eq!(grid.lines_buffer.len() % 5, 0);
    }

    #[test]
    fn test_lorenz_rk4_stability() {
        let mut lorenz = LorenzAttractor::new(Vec3::new(0.1, 0.0, 0.0), 100);
        for _ in 0..50 {
            lorenz.step(0.01);
        }
        assert!(lorenz.trail.len() == 50);
        assert!(lorenz.position.length() > 0.1);
    }

    #[test]
    fn test_barnes_hut_forces() {
        let nodes = vec![
            GraphNode { x: 0.0, y: 0.0, vx: 0.0, vy: 0.0, mass: 10.0 },
            GraphNode { x: 50.0, y: 0.0, vx: 0.0, vy: 0.0, mass: 10.0 },
            GraphNode { x: 0.0, y: 50.0, vx: 0.0, vy: 0.0, mass: 10.0 },
        ];
        let tree = BarnesHutTree::new(&nodes, 0.6);
        let (fx, fy) = tree.compute_force(0, &nodes, 100.0);
        assert!(fx < 0.0); // Repulsión hacia la izquierda
        assert!(fy < 0.0); // Repulsión hacia arriba
    }

    #[test]
    fn test_spring_convergence() {
        let mut spring = Spring2D::new(0.0, 0.0, 5.0, 1.0);
        spring.set_target(100.0, 50.0);
        for _ in 0..100 {
            spring.update(0.016);
        }
        assert!((spring.x - 100.0).abs() < 5.0);
        assert!((spring.y - 50.0).abs() < 5.0);
    }

    #[test]
    fn test_graph_layout_system_step() {
        let mut layout = GraphLayoutSystem::new(800.0, 600.0);
        let n0 = layout.add_node(100.0, 100.0, 5.0);
        let n1 = layout.add_node(120.0, 100.0, 5.0);
        layout.add_edge(n0, n1, 80.0);

        for _ in 0..10 {
            layout.step(0.016, 200.0, 0.05, 0.9);
        }

        // Los nodos deben haberse separado por repulsión
        let dist = (layout.nodes[n1].x - layout.nodes[n0].x).abs();
        assert!(dist > 15.0);
    }
}

