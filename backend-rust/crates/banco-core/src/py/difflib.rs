//! `difflib.SequenceMatcher` (sin isjunk, con autojunk) y `difflib.unified_diff` de Python 3.12, línea por
//! línea: los diffs que guarda la tabla `cambios` tienen que cortar en los mismos lugares.

use std::collections::HashMap;

struct Comparador<'a> {
    a: &'a [&'a str],
    b: &'a [&'a str],
    b2j: HashMap<&'a str, Vec<usize>>,
}

type Bloque = (usize, usize, usize);
type Op = (&'static str, usize, usize, usize, usize);

impl<'a> Comparador<'a> {
    fn nuevo(a: &'a [&'a str], b: &'a [&'a str]) -> Self {
        let mut b2j: HashMap<&'a str, Vec<usize>> = HashMap::new();
        for (i, elt) in b.iter().enumerate() {
            b2j.entry(*elt).or_default().push(i);
        }
        let n = b.len();
        if n >= 200 {
            let ntest = n / 100 + 1;
            b2j.retain(|_, idxs| idxs.len() <= ntest);
        }
        Comparador { a, b, b2j }
    }

    fn mas_largo(&self, alo: usize, ahi: usize, blo: usize, bhi: usize) -> Bloque {
        let (a, b) = (self.a, self.b);
        let (mut besti, mut bestj, mut bestsize) = (alo, blo, 0usize);
        let mut j2len: HashMap<usize, usize> = HashMap::new();
        for i in alo..ahi {
            let mut nuevo: HashMap<usize, usize> = HashMap::new();
            if let Some(js) = self.b2j.get(a[i]) {
                for &j in js {
                    if j < blo {
                        continue;
                    }
                    if j >= bhi {
                        break;
                    }
                    let k = if j > 0 { j2len.get(&(j - 1)).copied().unwrap_or(0) } else { 0 } + 1;
                    nuevo.insert(j, k);
                    if k > bestsize {
                        besti = i + 1 - k;
                        bestj = j + 1 - k;
                        bestsize = k;
                    }
                }
            }
            j2len = nuevo;
        }
        // sin basura explícita: solo se extiende por elementos iguales (los «populares» también)
        while besti > alo && bestj > blo && a[besti - 1] == b[bestj - 1] {
            besti -= 1;
            bestj -= 1;
            bestsize += 1;
        }
        while besti + bestsize < ahi && bestj + bestsize < bhi && a[besti + bestsize] == b[bestj + bestsize] {
            bestsize += 1;
        }
        (besti, bestj, bestsize)
    }

    fn bloques(&self) -> Vec<Bloque> {
        let (la, lb) = (self.a.len(), self.b.len());
        let mut cola = vec![(0, la, 0, lb)];
        let mut bloques: Vec<Bloque> = vec![];
        while let Some((alo, ahi, blo, bhi)) = cola.pop() {
            let (i, j, k) = self.mas_largo(alo, ahi, blo, bhi);
            if k > 0 {
                bloques.push((i, j, k));
                if alo < i && blo < j {
                    cola.push((alo, i, blo, j));
                }
                if i + k < ahi && j + k < bhi {
                    cola.push((i + k, ahi, j + k, bhi));
                }
            }
        }
        bloques.sort();
        let (mut i1, mut j1, mut k1) = (0, 0, 0);
        let mut salida = vec![];
        for (i2, j2, k2) in bloques {
            if i1 + k1 == i2 && j1 + k1 == j2 {
                k1 += k2;
            } else {
                if k1 > 0 {
                    salida.push((i1, j1, k1));
                }
                i1 = i2;
                j1 = j2;
                k1 = k2;
            }
        }
        if k1 > 0 {
            salida.push((i1, j1, k1));
        }
        salida.push((la, lb, 0));
        salida
    }

    fn opcodes(&self) -> Vec<Op> {
        let (mut i, mut j) = (0, 0);
        let mut salida = vec![];
        for (ai, bj, size) in self.bloques() {
            let tag = if i < ai && j < bj {
                "replace"
            } else if i < ai {
                "delete"
            } else if j < bj {
                "insert"
            } else {
                ""
            };
            if !tag.is_empty() {
                salida.push((tag, i, ai, j, bj));
            }
            i = ai + size;
            j = bj + size;
            if size > 0 {
                salida.push(("equal", ai, i, bj, j));
            }
        }
        salida
    }

    fn agrupados(&self, n: usize) -> Vec<Vec<Op>> {
        let mut codes = self.opcodes();
        if codes.is_empty() {
            codes = vec![("equal", 0, 1, 0, 1)];
        }
        if codes[0].0 == "equal" {
            let (t, i1, i2, j1, j2) = codes[0];
            codes[0] = (t, i1.max(i2.saturating_sub(n)), i2, j1.max(j2.saturating_sub(n)), j2);
        }
        let ultimo = codes.len() - 1;
        if codes[ultimo].0 == "equal" {
            let (t, i1, i2, j1, j2) = codes[ultimo];
            codes[ultimo] = (t, i1, i2.min(i1 + n), j1, j2.min(j1 + n));
        }
        let nn = n + n;
        let mut grupos = vec![];
        let mut grupo: Vec<Op> = vec![];
        for (tag, mut i1, i2, mut j1, j2) in codes {
            if tag == "equal" && i2 - i1 > nn {
                grupo.push((tag, i1, i2.min(i1 + n), j1, j2.min(j1 + n)));
                grupos.push(std::mem::take(&mut grupo));
                i1 = i1.max(i2.saturating_sub(n));
                j1 = j1.max(j2.saturating_sub(n));
            }
            grupo.push((tag, i1, i2, j1, j2));
        }
        if !grupo.is_empty() && !(grupo.len() == 1 && grupo[0].0 == "equal") {
            grupos.push(grupo);
        }
        grupos
    }
}

fn rango_unificado(inicio: usize, fin: usize) -> String {
    let mut comienzo = inicio + 1;
    let largo = fin - inicio;
    if largo == 1 {
        return format!("{comienzo}");
    }
    if largo == 0 {
        comienzo -= 1;
    }
    format!("{comienzo},{largo}")
}

/// `list(difflib.unified_diff(a, b, lineterm="", n=n))`.
pub fn unified_diff(a: &[&str], b: &[&str], n: usize) -> Vec<String> {
    let c = Comparador::nuevo(a, b);
    let mut salida = vec![];
    let mut empezado = false;
    for grupo in c.agrupados(n) {
        if !empezado {
            empezado = true;
            salida.push("--- ".to_string());
            salida.push("+++ ".to_string());
        }
        let (primero, ultimo) = (grupo[0], grupo[grupo.len() - 1]);
        salida.push(format!("@@ -{} +{} @@", rango_unificado(primero.1, ultimo.2), rango_unificado(primero.3, ultimo.4)));
        for (tag, i1, i2, j1, j2) in grupo {
            if tag == "equal" {
                for l in &a[i1..i2] {
                    salida.push(format!(" {l}"));
                }
                continue;
            }
            if tag == "replace" || tag == "delete" {
                for l in &a[i1..i2] {
                    salida.push(format!("-{l}"));
                }
            }
            if tag == "replace" || tag == "insert" {
                for l in &b[j1..j2] {
                    salida.push(format!("+{l}"));
                }
            }
        }
    }
    salida
}

#[cfg(test)]
mod pruebas {
    use super::*;

    #[test]
    fn como_python() {
        let a = ["a", "b", "c", "d", "e", "f", "g"];
        let b = ["a", "b", "x", "d", "e", "f", "g", "h"];
        assert_eq!(unified_diff(&a, &b, 2), vec!["--- ", "+++ ", "@@ -1,7 +1,8 @@", " a", " b", "-c", "+x", " d", " e", " f", " g", "+h"]);
        assert!(unified_diff(&[], &[], 2).is_empty());
    }
}
