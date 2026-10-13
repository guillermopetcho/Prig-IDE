//! Algoritmo Barnes-Hut con QuadTree 2D para simulación de fuerzas en grafos O(N log N).

#[derive(Debug, Clone, Copy)]
pub struct GraphNode {
    pub x: f32,
    pub y: f32,
    pub vx: f32,
    pub vy: f32,
    pub mass: f32,
}

#[derive(Debug, Clone)]
enum QuadNode {
    Empty,
    Leaf(usize), // Índice del nodo
    Internal {
        center_x: f32,
        center_y: f32,
        total_mass: f32,
        children: [Box<QuadNode>; 4],
    },
}

pub struct BarnesHutTree {
    root: QuadNode,
    theta: f32, // Umbral de aproximación (típicamente 0.6)
    pub min_x: f32,
    pub min_y: f32,
    pub size: f32,
}

impl BarnesHutTree {
    pub fn new(nodes: &[GraphNode], theta: f32) -> Self {
        if nodes.is_empty() {
            return Self {
                root: QuadNode::Empty,
                theta,
                min_x: 0.0,
                min_y: 0.0,
                size: 1.0,
            };
        }

        let mut min_x = f32::MAX;
        let mut max_x = f32::MIN;
        let mut min_y = f32::MAX;
        let mut max_y = f32::MIN;

        for n in nodes {
            min_x = min_x.min(n.x);
            max_x = max_x.max(n.x);
            min_y = min_y.min(n.y);
            max_y = max_y.max(n.y);
        }

        let pad = 20.0;
        let min_x = min_x - pad;
        let min_y = min_y - pad;
        let size = (max_x - min_x).max(max_y - min_y) + pad * 2.0;

        let mut tree = Self {
            root: QuadNode::Empty,
            theta,
            min_x,
            min_y,
            size,
        };

        for (i, _) in nodes.iter().enumerate() {
            tree.insert(i, nodes);
        }

        tree
    }

    fn insert(&mut self, node_idx: usize, nodes: &[GraphNode]) {
        let node = &nodes[node_idx];
        let root = core::mem::replace(&mut self.root, QuadNode::Empty);
        self.root = Self::insert_rec(root, node_idx, node.x, node.y, self.min_x, self.min_y, self.size, nodes);
    }

    fn insert_rec(
        current: QuadNode,
        new_idx: usize,
        nx: f32,
        ny: f32,
        bx: f32,
        by: f32,
        bsize: f32,
        nodes: &[GraphNode],
    ) -> QuadNode {
        match current {
            QuadNode::Empty => QuadNode::Leaf(new_idx),
            QuadNode::Leaf(old_idx) => {
                let half = bsize * 0.5;
                let mut children = [
                    Box::new(QuadNode::Empty),
                    Box::new(QuadNode::Empty),
                    Box::new(QuadNode::Empty),
                    Box::new(QuadNode::Empty),
                ];

                let old_node = &nodes[old_idx];
                let old_quad = Self::get_quadrant(old_node.x, old_node.y, bx, by, half);
                let (ox, oy) = Self::get_quad_origin(old_quad, bx, by, half);
                children[old_quad] = Box::new(Self::insert_rec(
                    QuadNode::Empty,
                    old_idx,
                    old_node.x,
                    old_node.y,
                    ox,
                    oy,
                    half,
                    nodes,
                ));

                let new_quad = Self::get_quadrant(nx, ny, bx, by, half);
                let (nx_orig, ny_orig) = Self::get_quad_origin(new_quad, bx, by, half);
                let existing = core::mem::replace(&mut children[new_quad], Box::new(QuadNode::Empty));
                children[new_quad] = Box::new(Self::insert_rec(
                    *existing,
                    new_idx,
                    nx,
                    ny,
                    nx_orig,
                    ny_orig,
                    half,
                    nodes,
                ));

                let total_mass = old_node.mass + nodes[new_idx].mass;
                let center_x = (old_node.x * old_node.mass + nx * nodes[new_idx].mass) / total_mass;
                let center_y = (old_node.y * old_node.mass + ny * nodes[new_idx].mass) / total_mass;

                QuadNode::Internal {
                    center_x,
                    center_y,
                    total_mass,
                    children,
                }
            }
            QuadNode::Internal {
                center_x,
                center_y,
                total_mass,
                mut children,
            } => {
                let half = bsize * 0.5;
                let new_mass = nodes[new_idx].mass;
                let new_total = total_mass + new_mass;
                let new_cx = (center_x * total_mass + nx * new_mass) / new_total;
                let new_cy = (center_y * total_mass + ny * new_mass) / new_total;

                let quad = Self::get_quadrant(nx, ny, bx, by, half);
                let (ox, oy) = Self::get_quad_origin(quad, bx, by, half);
                let existing = core::mem::replace(&mut children[quad], Box::new(QuadNode::Empty));
                children[quad] = Box::new(Self::insert_rec(*existing, new_idx, nx, ny, ox, oy, half, nodes));

                QuadNode::Internal {
                    center_x: new_cx,
                    center_y: new_cy,
                    total_mass: new_total,
                    children,
                }
            }
        }
    }

    #[inline(always)]
    fn get_quadrant(x: f32, y: f32, bx: f32, by: f32, half: f32) -> usize {
        let east = x >= bx + half;
        let south = y >= by + half;
        match (east, south) {
            (false, false) => 0, // NW
            (true, false) => 1,  // NE
            (false, true) => 2,  // SW
            (true, true) => 3,   // SE
        }
    }

    #[inline(always)]
    fn get_quad_origin(quad: usize, bx: f32, by: f32, half: f32) -> (f32, f32) {
        match quad {
            0 => (bx, by),
            1 => (bx + half, by),
            2 => (bx, by + half),
            3 => (bx + half, by + half),
            _ => (bx, by),
        }
    }

    /// Calcula la fuerza repulsiva resultante sobre un nodo dado usando Barnes-Hut.
    pub fn compute_force(&self, node_idx: usize, nodes: &[GraphNode], repulsion_constant: f32) -> (f32, f32) {
        let node = &nodes[node_idx];
        let mut fx = 0.0;
        let mut fy = 0.0;
        Self::force_rec(&self.root, node_idx, node.x, node.y, self.size, self.theta, repulsion_constant, nodes, &mut fx, &mut fy);
        (fx, fy)
    }

    fn force_rec(
        node: &QuadNode,
        idx: usize,
        x: f32,
        y: f32,
        size: f32,
        theta: f32,
        k: f32,
        nodes: &[GraphNode],
        fx: &mut f32,
        fy: &mut f32,
    ) {
        match node {
            QuadNode::Empty => {}
            QuadNode::Leaf(other_idx) => {
                if *other_idx != idx {
                    let other = &nodes[*other_idx];
                    let dx = x - other.x;
                    let dy = y - other.y;
                    let dist_sq = dx * dx + dy * dy + 10.0; // softening
                    let dist = dist_sq.sqrt();
                    let force = (k * other.mass) / dist_sq;
                    *fx += (dx / dist) * force;
                    *fy += (dy / dist) * force;
                }
            }
            QuadNode::Internal {
                center_x,
                center_y,
                total_mass,
                children,
            } => {
                let dx = x - *center_x;
                let dy = y - *center_y;
                let dist_sq = dx * dx + dy * dy + 10.0;
                let dist = dist_sq.sqrt();

                // Criterio Barnes-Hut: s / d < theta
                if (size / dist) < theta {
                    let force = (k * total_mass) / dist_sq;
                    *fx += (dx / dist) * force;
                    *fy += (dy / dist) * force;
                } else {
                    let half = size * 0.5;
                    for child in children {
                        Self::force_rec(child, idx, x, y, half, theta, k, nodes, fx, fy);
                    }
                }
            }
        }
    }
}

/// Sistema de simulación de layout de grafos de gran escala basado en fuerzas y Barnes-Hut.
#[derive(Debug, Clone, Default)]
pub struct GraphLayoutSystem {
    pub nodes: Vec<GraphNode>,
    pub edges: Vec<(usize, usize, f32)>, // (u, v, rest_length)
    pub width: f32,
    pub height: f32,
}

impl GraphLayoutSystem {
    pub fn new(width: f32, height: f32) -> Self {
        Self {
            nodes: Vec::new(),
            edges: Vec::new(),
            width: width.max(1.0),
            height: height.max(1.0),
        }
    }

    pub fn add_node(&mut self, x: f32, y: f32, mass: f32) -> usize {
        let idx = self.nodes.len();
        self.nodes.push(GraphNode {
            x,
            y,
            vx: 0.0,
            vy: 0.0,
            mass: mass.max(0.1),
        });
        idx
    }

    pub fn add_edge(&mut self, u: usize, v: usize, rest_length: f32) {
        if u < self.nodes.len() && v < self.nodes.len() && u != v {
            self.edges.push((u, v, rest_length.max(5.0)));
        }
    }

    pub fn clear(&mut self) {
        self.nodes.clear();
        self.edges.clear();
    }

    /// Ejecuta un paso de simulación física del grafo en O(N log N + E).
    pub fn step(&mut self, dt: f32, repulsion_k: f32, spring_k: f32, damping: f32) {
        let dt = dt.clamp(0.001, 0.04);
        let n_count = self.nodes.len();
        if n_count < 2 {
            return;
        }

        // 1. Árbol Barnes-Hut para repulsión electrostática O(N log N)
        let tree = BarnesHutTree::new(&self.nodes, 0.65);
        let mut fx = vec![0.0f32; n_count];
        let mut fy = vec![0.0f32; n_count];

        for i in 0..n_count {
            let (rx, ry) = tree.compute_force(i, &self.nodes, repulsion_k);
            fx[i] += rx;
            fy[i] += ry;

            // Gravedad suave hacia el centro del lienzo
            let cx = self.width * 0.5;
            let cy = self.height * 0.5;
            let center_dx = cx - self.nodes[i].x;
            let center_dy = cy - self.nodes[i].y;
            fx[i] += center_dx * 0.04;
            fy[i] += center_dy * 0.04;
        }

        // 2. Fuerzas elásticas atractivas de Hooke a lo largo de las aristas O(E)
        for &(u, v, rest_len) in &self.edges {
            let dx = self.nodes[v].x - self.nodes[u].x;
            let dy = self.nodes[v].y - self.nodes[u].y;
            let dist = (dx * dx + dy * dy).sqrt().max(0.1);
            let displacement = dist - rest_len;
            let spring_force = spring_k * displacement;

            let force_x = (dx / dist) * spring_force;
            let force_y = (dy / dist) * spring_force;

            fx[u] += force_x;
            fy[u] += force_y;
            fx[v] -= force_x;
            fy[v] -= force_y;
        }

        // 3. Integración de velocidad y amortiguamiento por fricción
        for i in 0..n_count {
            let inv_mass = 1.0 / self.nodes[i].mass;
            self.nodes[i].vx = (self.nodes[i].vx + fx[i] * inv_mass * dt) * damping;
            self.nodes[i].vy = (self.nodes[i].vy + fy[i] * inv_mass * dt) * damping;

            self.nodes[i].x += self.nodes[i].vx * dt;
            self.nodes[i].y += self.nodes[i].vy * dt;

            // Mantener dentro del espacio de vista
            self.nodes[i].x = self.nodes[i].x.clamp(20.0, self.width - 20.0);
            self.nodes[i].y = self.nodes[i].y.clamp(20.0, self.height - 20.0);
        }
    }
}


