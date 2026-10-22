//! El índice semántico de conceptos (`indice_semantico.py`): los vectores del embebedor y el parecido de cada
//! concepto con una pregunta. Python lo hacía con un bucle por dimensión (1000 conceptos de 1024 dimensiones, un
//! millón de vueltas por pregunta); aquí, con las mismas sumas en el mismo orden (los mismos bits) y en paralelo.

use std::collections::HashMap;

/// `_coseno` de Python: 0 si falta algo o las longitudes no casan; sumas en orden, en doble precisión
pub fn coseno(a: &[f64], b: &[f64]) -> f64 {
    if a.is_empty() || b.is_empty() || a.len() != b.len() {
        return 0.0;
    }
    let (mut producto, mut na, mut nb) = (0.0f64, 0.0f64, 0.0f64);
    for (x, y) in a.iter().zip(b) {
        producto += x * y;
        na += x * x;
        nb += y * y;
    }
    if na != 0.0 && nb != 0.0 {
        producto / (na * nb).sqrt()
    } else {
        0.0
    }
}

/// `struct.unpack("<n>f", b)` (orden de bytes de la máquina, como `struct` sin prefijo)
pub fn desempaquetar(b: &[u8]) -> Vec<f64> {
    b.as_chunks::<4>().0.iter().map(|c| f32::from_ne_bytes(*c) as f64).collect()
}

pub fn empaquetar(v: &[f64]) -> Vec<u8> {
    v.iter().flat_map(|&x| (x as f32).to_ne_bytes()).collect()
}

pub struct Vectores {
    ids: Vec<String>,
    datos: Vec<Vec<f64>>,
    posicion: HashMap<String, usize>,
}

impl Vectores {
    /// Las filas `(concept_id, vector)` en el orden de la base (con un id repetido, gana el último valor y se
    /// queda la primera posición, como al construir un dict)
    pub fn new(filas: Vec<(String, Vec<f64>)>) -> Vectores {
        let mut v = Vectores { ids: Vec::new(), datos: Vec::new(), posicion: HashMap::new() };
        for (id, datos) in filas {
            match v.posicion.get(&id) {
                Some(&i) => v.datos[i] = datos,
                None => {
                    v.posicion.insert(id.clone(), v.ids.len());
                    v.ids.push(id);
                    v.datos.push(datos);
                }
            }
        }
        v
    }

    pub fn len(&self) -> usize {
        self.ids.len()
    }

    pub fn is_empty(&self) -> bool {
        self.ids.is_empty()
    }

    pub fn contiene(&self, id: &str) -> bool {
        self.posicion.contains_key(id)
    }

    /// Las posiciones de los candidatos: los pedidos que estén (en su orden, repetidos incluidos) o todos
    pub fn candidatos(&self, ids: Option<&[String]>) -> Vec<usize> {
        match ids {
            Some(ids) if !ids.is_empty() => ids.iter().filter_map(|id| self.posicion.get(id).copied()).collect(),
            _ => (0..self.ids.len()).collect(),
        }
    }

    pub fn dimension_de(&self, i: usize) -> usize {
        self.datos[i].len()
    }

    /// `sorted(((_coseno(q, v), cid) for ...), reverse=True)`: de más a menos parecido; a igual parecido, el id mayor
    pub fn puntuar(&self, q: &[f64], candidatos: &[usize]) -> Vec<(f64, String)> {
        let puntuar = |&i: &usize| (coseno(q, &self.datos[i]), i);
        let hilos = std::thread::available_parallelism().map_or(1, |n| n.get()).min(8);
        let mut v: Vec<(f64, usize)> = if candidatos.len() * q.len() < 200_000 || hilos == 1 {
            candidatos.iter().map(puntuar).collect()
        } else {
            let trozo = candidatos.len().div_ceil(hilos);
            std::thread::scope(|s| {
                let tareas: Vec<_> = candidatos.chunks(trozo).map(|c| s.spawn(move || c.iter().map(puntuar).collect::<Vec<_>>())).collect();
                tareas.into_iter().flat_map(|t| t.join().unwrap()).collect()
            })
        };
        v.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal).then_with(|| self.ids[b.1].cmp(&self.ids[a.1])));
        v.into_iter().map(|(s, i)| (s, self.ids[i].clone())).collect()
    }
}

#[cfg(test)]
mod pruebas {
    use super::*;

    #[test]
    fn coseno_como_python() {
        assert_eq!(coseno(&[1.0, 0.0], &[1.0, 0.0]), 1.0);
        assert_eq!(coseno(&[], &[1.0]), 0.0);
        assert_eq!(coseno(&[0.0, 0.0], &[0.0, 0.0]), 0.0);
    }

    #[test]
    fn ordena_como_sorted_reverse() {
        let v = Vectores::new(vec![("a".into(), vec![1.0, 0.0]), ("b".into(), vec![1.0, 0.0]), ("c".into(), vec![0.0, 1.0])]);
        let r = v.puntuar(&[1.0, 0.0], &v.candidatos(None));
        assert_eq!(r.iter().map(|x| x.1.as_str()).collect::<Vec<_>>(), ["b", "a", "c"]);
    }
}
