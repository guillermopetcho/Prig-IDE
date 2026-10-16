//! Las referencias del catálogo que vienen al caso de una pregunta (`relacionadas` de `referencias_ml.py` y
//! `referencias_dp.py`). Python normalizaba los temas y compilaba una expresión por tema y referencia en cada
//! pregunta (76 ms con 387 referencias); aquí el catálogo se normaliza una vez y la pregunta se recorre con
//! búsquedas de texto. Mismo resultado: la normalización de `_normalizar`, el plural de `_aparece` y la suma
//! compensada de `sum()` de Python 3.12 (los empates se ordenan igual).

use crate::indices::Suma;
use std::collections::{HashMap, HashSet};
use unicode_normalization::char::canonical_combining_class;
use unicode_normalization::UnicodeNormalization;

/// `_normalizar`: minúsculas, NFKD y sin marcas combinantes
pub fn normalizar(t: &str) -> String {
    t.to_lowercase().nfkd().filter(|&c| canonical_combining_class(c) == 0).collect()
}

fn alnum_ascii(c: Option<char>) -> bool {
    c.is_some_and(|c| c.is_ascii_lowercase() || c.is_ascii_digit())
}

/// `re.search(r"(?<![a-z0-9])" + re.escape(clave) + r"(?:s|es)?(?![a-z0-9])", texto)`
pub fn aparece(clave: &str, texto: &str) -> bool {
    if clave.is_empty() {
        // el patrón vacío casa en cualquier sitio que no esté entre [a-z0-9]
        let cs: Vec<char> = texto.chars().collect();
        return (0..=cs.len()).any(|i| {
            !alnum_ascii(if i > 0 { Some(cs[i - 1]) } else { None })
                && ["", "s", "es"].iter().any(|suf| {
                    let n = suf.chars().count();
                    cs.get(i..i + n).is_some_and(|w| w.iter().copied().eq(suf.chars())) && !alnum_ascii(cs.get(i + n).copied())
                })
        });
    }
    let mut desde = 0;
    while let Some(k) = texto[desde..].find(clave) {
        let ini = desde + k;
        let fin = ini + clave.len();
        if !alnum_ascii(texto[..ini].chars().next_back()) {
            let resto = &texto[fin..];
            let ok = ["s", "es", ""]
                .iter()
                .any(|suf| resto.starts_with(suf) && !alnum_ascii(resto[suf.len()..].chars().next()));
            if ok {
                return true;
            }
        }
        desde = ini + texto[ini..].chars().next().map_or(1, char::len_utf8);
    }
    false
}

pub struct Categoria {
    pub id: String,
    pub claves: Vec<String>,
}

pub struct Referencia {
    pub caida: bool,
    pub categorias: Vec<String>,
    pub temas: Vec<String>,
    pub titulo: String,
    pub tipo: Option<String>,
}

struct Ref {
    caida: bool,
    categorias: Vec<String>,
    /// temas normalizados, sin los genéricos (para `propios`, solo cuentan los de más de 2 caracteres)
    temas: Vec<String>,
    titulo: String,
    peso: f64,
    tipo: Option<String>,
}

pub struct Catalogo {
    categorias: Vec<(String, Vec<(String, f64)>)>,
    refs: Vec<Ref>,
}

fn peso_tipo(t: Option<&str>) -> f64 {
    match t {
        Some("formulario") => 1.2,
        Some("libro") => 1.5,
        Some("apuntes") => 1.0,
        Some("survey") => 1.1,
        Some("paper") => 0.8,
        Some("articulo") => 0.6,
        Some("documentacion") => 0.4,
        _ => 0.5,
    }
}

impl Catalogo {
    pub fn new(categorias: Vec<Categoria>, refs: Vec<Referencia>, genericos: &HashSet<String>) -> Catalogo {
        Catalogo {
            categorias: categorias
                .into_iter()
                .map(|c| {
                    let claves = c.claves.into_iter().map(|k| {
                        let n = k.split(|ch: char| ch.is_whitespace() || ('\x1c'..='\x1f').contains(&ch)).filter(|w| !w.is_empty()).count();
                        (k, 1.0 + 0.2 * n as f64)
                    });
                    (c.id, claves.collect())
                })
                .collect(),
            refs: refs
                .into_iter()
                .map(|r| Ref {
                    caida: r.caida,
                    categorias: r.categorias,
                    temas: r.temas.iter().map(|t| normalizar(t)).filter(|t| !genericos.contains(t)).collect(),
                    titulo: normalizar(&r.titulo),
                    peso: peso_tipo(r.tipo.as_deref()),
                    tipo: r.tipo,
                })
                .collect(),
        }
    }

    /// Las posiciones de las referencias elegidas, en orden (`relacionadas`)
    pub fn relacionadas(&self, texto: &str, maximo: usize) -> Vec<usize> {
        let t = normalizar(texto);
        if t.chars().count() < 3 {
            return Vec::new();
        }
        let mut puntos_cat: HashMap<&str, f64> = HashMap::new();
        for (id, claves) in &self.categorias {
            let mut n = Suma::default();
            let mut alguna = false;
            for (k, peso) in claves {
                if aparece(k, &t) {
                    n.mas(*peso);
                    alguna = true;
                }
            }
            // `if n:` (una suma que diera 0.0 tampoco cuenta)
            if alguna && n.valor() != 0.0 {
                puntos_cat.insert(id, n.valor());
            }
        }
        let mut candidatas: Vec<(f64, usize)> = Vec::new();
        for (i, r) in self.refs.iter().enumerate() {
            if r.caida {
                continue;
            }
            let mut p = Suma::default();
            for (j, c) in r.categorias.iter().enumerate() {
                p.mas(puntos_cat.get(c.as_str()).copied().unwrap_or(0.0) * if j == 0 { 1.0 } else { 0.5 });
            }
            let p = p.valor();
            let mut propios = Suma::default();
            for x in &r.temas {
                if x.chars().count() > 2 && aparece(x, &t) {
                    propios.mas(2.5);
                }
            }
            let mut propios = propios.valor();
            if r.titulo.chars().count() > 8 && t.contains(&r.titulo) {
                propios += 6.0;
            }
            if p == 0.0 && propios == 0.0 {
                continue;
            }
            candidatas.push((p + propios + r.peso * if p != 0.0 { 1.0 } else { 0.0 }, i));
        }
        // `sort(key=-puntos)`: estable
        candidatas.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));
        let mut elegidas = Vec::new();
        let mut por_tipo: HashMap<Option<&str>, usize> = HashMap::new();
        for (puntos, i) in candidatas {
            if puntos < 2.0 {
                break;
            }
            let tipo = self.refs[i].tipo.as_deref();
            let n = por_tipo.entry(tipo).or_insert(0);
            if *n >= 2 {
                continue;
            }
            *n += 1;
            elegidas.push(i);
            if elegidas.len() >= maximo {
                break;
            }
        }
        elegidas
    }
}

#[cfg(test)]
mod pruebas {
    use super::*;

    #[test]
    fn aparece_con_plural() {
        assert!(aparece("transformer", "los transformers son"));
        assert!(aparece("red", "una red."));
        assert!(!aparece("red neuronal", "redes neuronales"));
        assert!(!aparece("arbol", "subarbol"));
        assert!(aparece("arbol", "arboles"));
    }

    #[test]
    fn normaliza_como_python() {
        assert_eq!(normalizar("Árbol ÑANDÚ ﬁ"), "arbol nandu fi");
    }
}
