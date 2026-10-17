//! Los índices de la biblioteca (`knowledge/indexing/bm25_index.py` y `vector_index.py`): BM25 Okapi y TF-IDF
//! con coseno, sobre los fragmentos del catálogo. En Python cada fragmento era un diccionario de términos y cada
//! búsqueda los recorría todos; aquí cada término guarda la lista de fragmentos que lo contienen y una búsqueda
//! solo toca esos. Las puntuaciones salen con los mismos bits: las mismas operaciones en el mismo orden (también
//! la suma compensada de `sum()` de Python 3.12 en el coseno).

use std::collections::HashMap;

/// `re.findall(r'\w+', texto.lower())`: `\w` de Python sobre textos (letras y números Unicode, y «_»)
pub fn tokenizar(texto: &str) -> Vec<String> {
    let bajo = texto.to_lowercase();
    let mut salida = Vec::new();
    let mut actual = String::new();
    for c in bajo.chars() {
        if c.is_alphanumeric() || c == '_' {
            actual.push(c);
        } else if !actual.is_empty() {
            salida.push(std::mem::take(&mut actual));
        }
    }
    if !actual.is_empty() {
        salida.push(actual);
    }
    salida
}

/// Términos → números, para no guardar el mismo texto mil veces
#[derive(Default)]
struct Vocabulario {
    ids: HashMap<String, u32>,
}

impl Vocabulario {
    fn id(&mut self, t: &str) -> u32 {
        if let Some(i) = self.ids.get(t) {
            return *i;
        }
        let i = self.ids.len() as u32;
        self.ids.insert(t.to_string(), i);
        i
    }
}

/// Las frecuencias de un texto en el orden en que aparece cada término por primera vez (el de un dict)
fn frecuencias(vocab: &mut Vocabulario, tokens: &[String]) -> Vec<(u32, u32)> {
    let mut orden: Vec<(u32, u32)> = Vec::new();
    let mut pos: HashMap<u32, usize> = HashMap::new();
    for t in tokens {
        let id = vocab.id(t);
        match pos.get(&id) {
            Some(&i) => orden[i].1 += 1,
            None => {
                pos.insert(id, orden.len());
                orden.push((id, 1));
            }
        }
    }
    orden
}

fn ordenar(mut puntos: Vec<(usize, f64)>, top_k: usize) -> Vec<(usize, f64)> {
    // `sort(key=score, reverse=True)` de Python: estable (los empates, en el orden del corpus)
    puntos.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal).then(a.0.cmp(&b.0)));
    puntos.truncate(top_k);
    puntos
}

pub struct Bm25 {
    k1: f64,
    b: f64,
    vocab: Vocabulario,
    /// término → [(fragmento, frecuencia)]
    listas: Vec<Vec<(u32, u32)>>,
    idf: Vec<f64>,
    largo: Vec<usize>,
    medio: f64,
}

impl Bm25 {
    pub fn new(textos: &[String], k1: f64, b: f64) -> Bm25 {
        let mut vocab = Vocabulario::default();
        let mut listas: Vec<Vec<(u32, u32)>> = Vec::new();
        let mut largo = Vec::with_capacity(textos.len());
        let mut total = 0usize;
        for (d, texto) in textos.iter().enumerate() {
            let tokens = tokenizar(texto);
            largo.push(tokens.len());
            total += tokens.len();
            for (id, f) in frecuencias(&mut vocab, &tokens) {
                if listas.len() <= id as usize {
                    listas.resize_with(id as usize + 1, Vec::new);
                }
                listas[id as usize].push((d as u32, f));
            }
        }
        let n = textos.len() as f64;
        let medio = if textos.is_empty() { 0.0 } else { total as f64 / n };
        let idf = listas.iter().map(|l| ((n - l.len() as f64 + 0.5) / (l.len() as f64 + 0.5) + 1.0).ln()).collect();
        Bm25 { k1, b, vocab, listas, idf, largo, medio }
    }

    pub fn documentos(&self) -> usize {
        self.largo.len()
    }

    /// `search(query, top_k)`: (fragmento, puntuación) de mayor a menor
    pub fn buscar(&self, consulta: &str, top_k: usize) -> Vec<(usize, f64)> {
        if self.largo.is_empty() {
            return vec![];
        }
        let mut puntos = vec![0.0f64; self.largo.len()];
        let mut tocados: Vec<usize> = Vec::new();
        for t in tokenizar(consulta) {
            let Some(&id) = self.vocab.ids.get(&t) else { continue };
            let idf = self.idf[id as usize];
            for &(d, f) in &self.listas[id as usize] {
                let d = d as usize;
                let f = f as f64;
                let num = idf * f * (self.k1 + 1.0);
                let den = f + self.k1 * (1.0 - self.b + self.b * (self.largo[d] as f64 / self.medio));
                if puntos[d] == 0.0 {
                    tocados.push(d);
                }
                puntos[d] += num / den;
            }
        }
        tocados.sort_unstable();
        tocados.dedup();
        ordenar(tocados.into_iter().filter(|&d| puntos[d] > 0.0).map(|d| (d, puntos[d])).collect(), top_k)
    }
}

/// `sum()` de Python 3.12, de a un sumando: el primero se suma a 0 y el resto con la compensación de Neumaier
#[derive(Clone, Copy, Default)]
pub(crate) struct Suma {
    f: f64,
    c: f64,
    empezada: bool,
}

impl Suma {
    pub(crate) fn mas(&mut self, x: f64) {
        if !self.empezada {
            self.f = 0.0 + x;
            self.empezada = true;
            return;
        }
        let t = self.f + x;
        if self.f.abs() >= x.abs() {
            self.c += (self.f - t) + x;
        } else {
            self.c += (x - t) + self.f;
        }
        self.f = t;
    }

    pub(crate) fn valor(&self) -> f64 {
        if self.c != 0.0 && self.c.is_finite() {
            self.f + self.c
        } else {
            self.f
        }
    }
}

pub struct Vectorial {
    vocab: Vocabulario,
    /// término → [(fragmento, peso normalizado)]
    listas: Vec<Vec<(u32, f64)>>,
    documentos: usize,
}

impl Vectorial {
    pub fn new(textos: &[String]) -> Vectorial {
        let mut vocab = Vocabulario::default();
        let tokens: Vec<Vec<String>> = textos.iter().map(|t| tokenizar(t)).collect();
        let por_doc: Vec<Vec<(u32, u32)>> = tokens.iter().map(|t| frecuencias(&mut vocab, t)).collect();
        let mut df = vec![0u32; vocab.ids.len()];
        for f in &por_doc {
            for (id, _) in f {
                df[*id as usize] += 1;
            }
        }
        let n = textos.len() as f64;
        let mut listas: Vec<Vec<(u32, f64)>> = vec![Vec::new(); vocab.ids.len()];
        for (d, f) in por_doc.iter().enumerate() {
            let largo = tokens[d].len() as f64;
            let mut valores = Vec::with_capacity(f.len());
            let mut norma = 0.0f64;
            for (id, freq) in f {
                let idf = ((n + 1.0) / (df[*id as usize] as f64 + 1.0)).ln();
                let v = (*freq as f64 / largo) * idf;
                valores.push((*id, v));
                norma += v * v;
            }
            let norma = if norma > 0.0 { norma.sqrt() } else { 1.0 };
            for (id, v) in valores {
                listas[id as usize].push((d as u32, v / norma));
            }
        }
        Vectorial { vocab, listas, documentos: textos.len() }
    }

    pub fn documentos(&self) -> usize {
        self.documentos
    }

    /// `search(query, top_k)`: coseno con la consulta (TF normalizado), de mayor a menor
    pub fn buscar(&self, consulta: &str, top_k: usize) -> Vec<(usize, f64)> {
        if self.documentos == 0 {
            return vec![];
        }
        let tokens = tokenizar(consulta);
        if tokens.is_empty() {
            return vec![];
        }
        // las frecuencias de la consulta, en el orden de un dict
        let mut q: Vec<(String, u64)> = Vec::new();
        for t in tokens {
            match q.iter_mut().find(|x| x.0 == t) {
                Some(x) => x.1 += 1,
                None => q.push((t, 1)),
            }
        }
        let norma_cuadrada: u64 = q.iter().map(|x| x.1 * x.1).sum();
        let qn = if norma_cuadrada == 0 { 1.0 } else { (norma_cuadrada as f64).sqrt() };
        let mut sumas: HashMap<usize, Suma> = HashMap::new();
        for (t, f) in &q {
            let Some(&id) = self.vocab.ids.get(t) else { continue };
            let qv = *f as f64 / qn;
            for &(d, v) in &self.listas[id as usize] {
                sumas.entry(d as usize).or_default().mas(qv * v);
            }
        }
        let puntos: Vec<(usize, f64)> = sumas.into_iter().map(|(d, s)| (d, s.valor())).filter(|x| x.1 > 0.0).collect();
        ordenar(puntos, top_k)
    }
}

/// `sum(v)` de Python 3.12 sobre reales (con su suma compensada)
pub(crate) fn suma_py(v: &[f64]) -> f64 {
    let mut s = Suma { f: 0.0, c: 0.0, empezada: false };
    for x in v {
        s.mas(*x);
    }
    if s.empezada { s.valor() } else { 0.0 }
}
