//! Un `set` de enteros de CPython 3.12, con su tabla hash: el orden en que Python recorre un conjunto de
//! enteros depende de las ranuras (hash & máscara, sondeo lineal de 9 y perturbación), no del valor ni del
//! orden de inserción. La partición desempata por ese orden (particion_proyecto.ordenar): para obtener las
//! mismas unidades hay que recorrer los conjuntos igual.

const MIN: usize = 8;
const SONDEO_LINEAL: usize = 9;
const PERTURBACION: u32 = 5;

#[derive(Clone, Debug)]
pub struct ConjuntoInt {
    tabla: Vec<Option<i64>>,
    mascara: usize,
    llenas: usize,
    usadas: usize,
}

impl Default for ConjuntoInt {
    fn default() -> Self {
        Self::nuevo()
    }
}

fn hash(x: i64) -> u64 {
    // hash(int) de CPython para |x| < 2^61: el valor, salvo -1 → -2
    if x == -1 {
        (-2i64) as u64
    } else {
        x as u64
    }
}

impl ConjuntoInt {
    pub fn nuevo() -> Self {
        ConjuntoInt { tabla: vec![None; MIN], mascara: MIN - 1, llenas: 0, usadas: 0 }
    }

    pub fn len(&self) -> usize {
        self.usadas
    }

    pub fn is_empty(&self) -> bool {
        self.usadas == 0
    }

    fn ranura(&self, x: i64) -> Result<usize, usize> {
        // Ok(i): ya está en i; Err(i): primera ranura libre en el recorrido de sondeo
        let h = hash(x);
        let mascara = self.mascara;
        let mut i = (h as usize) & mascara;
        let mut perturbacion = h;
        loop {
            let sondeos = if i + SONDEO_LINEAL <= mascara { SONDEO_LINEAL } else { 0 };
            for j in 0..=sondeos {
                match self.tabla[i + j] {
                    None => return Err(i + j),
                    Some(y) if y == x => return Ok(i + j),
                    _ => {}
                }
            }
            perturbacion >>= PERTURBACION;
            i = (i.wrapping_mul(5).wrapping_add(1).wrapping_add(perturbacion as usize)) & mascara;
        }
    }

    pub fn contiene(&self, x: i64) -> bool {
        self.ranura(x).is_ok()
    }

    /// `s.add(x)`; true si era nuevo.
    pub fn agregar(&mut self, x: i64) -> bool {
        match self.ranura(x) {
            Ok(_) => false,
            Err(i) => {
                self.tabla[i] = Some(x);
                self.llenas += 1;
                self.usadas += 1;
                if self.llenas * 5 >= self.mascara * 3 {
                    let minimo = if self.usadas > 50000 { self.usadas * 2 } else { self.usadas * 4 };
                    self.redimensionar(minimo);
                }
                true
            }
        }
    }

    fn redimensionar(&mut self, minimo: usize) {
        let mut nuevo = MIN;
        while nuevo <= minimo {
            nuevo <<= 1;
        }
        let vieja = std::mem::replace(&mut self.tabla, vec![None; nuevo]);
        self.mascara = nuevo - 1;
        self.llenas = self.usadas;
        for x in vieja.into_iter().flatten() {
            self.insertar_limpio(x);
        }
    }

    fn insertar_limpio(&mut self, x: i64) {
        let h = hash(x);
        let mascara = self.mascara;
        let mut i = (h as usize) & mascara;
        let mut perturbacion = h;
        loop {
            if self.tabla[i].is_none() {
                self.tabla[i] = Some(x);
                return;
            }
            if i + SONDEO_LINEAL <= mascara {
                for j in 1..=SONDEO_LINEAL {
                    if self.tabla[i + j].is_none() {
                        self.tabla[i + j] = Some(x);
                        return;
                    }
                }
            }
            perturbacion >>= PERTURBACION;
            i = (i.wrapping_mul(5).wrapping_add(1).wrapping_add(perturbacion as usize)) & mascara;
        }
    }

    /// Los elementos en el orden en que los recorre Python.
    pub fn iter(&self) -> impl Iterator<Item = i64> + '_ {
        self.tabla.iter().filter_map(|x| *x)
    }
}

#[cfg(test)]
mod pruebas {
    use super::*;

    #[test]
    fn orden_como_cpython() {
        let mut s = ConjuntoInt::nuevo();
        for x in [5, 100, 13, 2, 64, 9] {
            s.agregar(x);
        }
        assert_eq!(s.iter().collect::<Vec<_>>(), vec![64, 2, 100, 5, 9, 13]);
        let mut s2 = ConjuntoInt::nuevo();
        for x in (3..=30).rev().step_by(3) {
            s2.agregar(x);
        }
        assert_eq!(s2.iter().collect::<Vec<_>>(), (1..=10).map(|k| k * 3).collect::<Vec<_>>());
    }
}
