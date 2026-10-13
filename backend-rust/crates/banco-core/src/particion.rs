//! Partición del proyecto en unidades de lectura (particion_proyecto.py). Es lo que decide el texto de cada
//! unidad guardada por el motor: tiene que salir idéntica a la de Python, también en los desempates. Por eso:
//! diccionarios con el orden de inserción de Python (IndexMap, con «pop» que no reordena), los `defaultdict`
//! que crean la clave al leerla, conjuntos de enteros recorridos como CPython (ConjuntoInt), `sum` de 3.12 y
//! `round` al par.

use std::collections::{HashMap, HashSet};
use std::process::{Command, Stdio};
use std::time::Instant;

use indexmap::IndexMap;
use serde_json::{json, Map, Value};

use crate::banco::{descomprimir, error, Banco, Resultado};
use crate::extraer::ES_TEST;
use crate::py::cadena::{largo, splitlines, strip};
use crate::py::conjunto::ConjuntoInt;
use crate::py::numero::{round, round_entero, suma};
use crate::py::ruta::{basename, commonpath, dirname};

pub const PRESUPUESTO_UNIDAD: i64 = 16000;
const LENGUAJES_CODIGO: [&str; 6] = ["python", "js", "c", "go", "rust", "java"];

pub fn es_produccion(ruta: &str, lenguaje: &str) -> bool {
    LENGUAJES_CODIGO.contains(&lenguaje) && !ES_TEST.hay(ruta)
}

#[derive(Clone, Debug)]
pub struct Sim {
    pub nombre: String,
    pub padre: String,
    pub ini: i64,
    pub fin: i64,
}

#[derive(Clone, Debug)]
pub struct Pieza {
    pub ruta: String,
    pub ini: i64,
    pub fin: i64,
    pub tokens: i64,
    pub simbolos: Vec<String>,
}

/// Las líneas de un archivo con su largo en caracteres (para estimar tokens sin unir texto).
struct Lineas {
    largos: Vec<usize>,
}

impl Lineas {
    /// `_tokens_de(lineas, ini, fin)`: estimar_tokens("\n".join(lineas[ini - 1:fin])).
    fn tokens(&self, ini: i64, fin: i64) -> i64 {
        let n = self.largos.len() as i64;
        let a = (ini - 1).clamp(0, n) as usize;
        let b = fin.clamp(0, n) as usize;
        let chars = if a < b { self.largos[a..b].iter().sum::<usize>() + (b - a - 1) } else { 0 };
        (chars as f64 / crate::texto::CARACTERES_POR_TOKEN) as i64 + 1
    }
}

/// `piezas_de_archivo`: el archivo entero si cabe; si no, grupos de símbolos de primer nivel, luego métodos y
/// por último líneas.
pub fn piezas_de_archivo(ruta: &str, lineas: &[&str], simbolos: &[Sim], tokens: i64, tope: i64) -> Vec<Pieza> {
    let total = lineas.len() as i64;
    let primer_nivel: Vec<&Sim> = simbolos.iter().filter(|s| s.padre.is_empty()).collect();
    if tokens <= tope || total == 0 {
        return vec![Pieza { ruta: ruta.to_string(), ini: 1, fin: total.max(1), tokens, simbolos: primer_nivel.iter().map(|s| s.nombre.clone()).collect() }];
    }
    let l = Lineas { largos: lineas.iter().map(|x| largo(x)).collect() };
    let mut primer = primer_nivel.clone();
    primer.sort_by_key(|s| s.ini);
    let mut tramos: Vec<(i64, i64, Vec<String>, Option<&Sim>)> = vec![];
    let mut cursor = 1;
    for s in &primer {
        if s.fin < cursor {
            continue;
        }
        tramos.push((cursor, s.fin, vec![s.nombre.clone()], Some(*s)));
        cursor = s.fin + 1;
    }
    if cursor <= total {
        tramos.push((cursor, total, vec![], None));
    }
    if tramos.is_empty() {
        tramos.push((1, total, vec![], None));
    }
    let mut finos: Vec<(i64, i64, Vec<String>)> = vec![];
    for (ini, fin, nombres, s) in tramos {
        if l.tokens(ini, fin) <= tope {
            finos.push((ini, fin, nombres));
            continue;
        }
        let mut hijos: Vec<&Sim> = match s {
            Some(s) => simbolos.iter().filter(|h| h.padre == s.nombre).collect(),
            None => vec![],
        };
        hijos.sort_by_key(|h| h.ini);
        let mut cur = ini;
        for h in &hijos {
            if h.fin < cur {
                continue;
            }
            finos.push((cur, h.fin, vec![h.nombre.clone()]));
            cur = h.fin + 1;
        }
        if cur <= fin {
            finos.push((cur, fin, if hijos.is_empty() { nombres } else { vec![] }));
        }
    }
    let mut cortados: Vec<(i64, i64, Vec<String>)> = vec![];
    for (ini, fin, nombres) in finos {
        if l.tokens(ini, fin) <= tope {
            cortados.push((ini, fin, nombres));
            continue;
        }
        let (mut a, mut acumulado, mut primero) = (ini, 0i64, true);
        for n in ini..=fin {
            let t = l.tokens(n, n);
            if acumulado + t > tope && n > a {
                cortados.push((a, n - 1, if primero { nombres.clone() } else { vec![] }));
                a = n;
                acumulado = 0;
                primero = false;
            }
            acumulado += t;
        }
        cortados.push((a, fin, if primero { nombres } else { vec![] }));
    }
    let mut piezas: Vec<Pieza> = vec![];
    let mut actual: Option<Pieza> = None;
    for (ini, fin, nombres) in cortados {
        let t = l.tokens(ini, fin);
        match actual.as_mut() {
            Some(p) if p.tokens + t <= tope => {
                p.fin = fin;
                p.tokens += t;
                p.simbolos.extend(nombres);
            }
            _ => {
                if let Some(p) = actual.take() {
                    piezas.push(p);
                }
                actual = Some(Pieza { ruta: ruta.to_string(), ini, fin, tokens: t, simbolos: nombres });
            }
        }
    }
    if let Some(p) = actual {
        piezas.push(p);
    }
    piezas
}

type Indice = IndexMap<String, Vec<(i64, i64, usize)>>;

/// `_pieza_de`: la pieza que contiene la línea (o la primera del archivo).
fn pieza_de(indice: &Indice, ruta: &str, linea: i64) -> Option<usize> {
    let lista = indice.get(ruta)?;
    for (ini, fin, i) in lista {
        if *ini <= linea && linea <= *fin {
            return Some(*i);
        }
    }
    lista.first().map(|x| x.2)
}

struct Grafo {
    indice: Indice,
    inicio_simbolo: HashMap<(String, String), i64>,
    llamadas: Vec<(String, String, String, String, i64)>,
    importaciones: Vec<(String, String)>,
}

fn sumar(pesos: &mut IndexMap<(usize, usize), f64>, a: Option<usize>, b: Option<usize>, w: f64) {
    let (Some(a), Some(b)) = (a, b) else { return };
    if a == b {
        return;
    }
    let clave = (a.min(b), a.max(b));
    let previo = pesos.get(&clave).copied().unwrap_or(0.0);
    pesos.insert(clave, previo + w);
}

impl Grafo {
    fn destino(&self, a_ruta: &str, a_nombre: &str) -> Option<usize> {
        let linea = *self.inicio_simbolo.get(&(a_ruta.to_string(), a_nombre.to_string()))?;
        if linea == 0 {
            return None;
        }
        pieza_de(&self.indice, a_ruta, linea)
    }

    /// `pesos_entre_piezas`: llamadas (1), imports (2) y piezas contiguas del mismo archivo (3).
    fn pesos(&self) -> IndexMap<(usize, usize), f64> {
        let mut pesos: IndexMap<(usize, usize), f64> = IndexMap::new();
        for (ruta, _desde, a_ruta, a_nombre, linea) in &self.llamadas {
            let a = pieza_de(&self.indice, ruta, *linea);
            let b = self.destino(a_ruta, a_nombre);
            sumar(&mut pesos, a, b, 1.0);
        }
        for (ruta, destino) in &self.importaciones {
            if let (Some(x), Some(y)) = (self.indice.get(ruta), self.indice.get(destino)) {
                sumar(&mut pesos, Some(x[0].2), Some(y[0].2), 2.0);
            }
        }
        for lista in self.indice.values() {
            let mut orden = lista.clone();
            orden.sort();
            for par in orden.windows(2) {
                sumar(&mut pesos, Some(par[0].2), Some(par[1].2), 3.0);
            }
        }
        pesos
    }

    /// `dirigidas_entre_piezas`: (quien llama, a quien) → cantidad.
    fn dirigidas(&self) -> IndexMap<(usize, usize), f64> {
        let mut d: IndexMap<(usize, usize), f64> = IndexMap::new();
        for (ruta, _desde, a_ruta, a_nombre, linea) in &self.llamadas {
            let a = pieza_de(&self.indice, ruta, *linea);
            let b = self.destino(a_ruta, a_nombre);
            if let (Some(a), Some(b)) = (a, b) {
                if a != b {
                    let previo = d.get(&(a, b)).copied().unwrap_or(0.0);
                    d.insert((a, b), previo + 1.0);
                }
            }
        }
        d
    }
}

/// `_carpeta`: los dos primeros niveles de la carpeta.
fn carpeta(ruta: &str) -> String {
    let partes: Vec<&str> = ruta.split('/').collect();
    let carpetas = &partes[..partes.len() - 1];
    carpetas.iter().take(2).cloned().collect::<Vec<_>>().join("/")
}

struct Grupo {
    piezas: Vec<usize>,
    tokens: i64,
    carpetas: HashSet<String>,
}

/// `agrupar`: aglomerativo con tope; después lo suelto por carpeta y lo muy chico con lo que sea.
pub fn agrupar(piezas: &[Pieza], pesos: &IndexMap<(usize, usize), f64>, tope: i64) -> Vec<Vec<usize>> {
    let mut grupos: IndexMap<usize, Grupo> = IndexMap::new();
    for (i, p) in piezas.iter().enumerate() {
        grupos.insert(i, Grupo { piezas: vec![i], tokens: p.tokens, carpetas: [carpeta(&p.ruta)].into_iter().collect() });
    }
    // defaultdict(dict): un dict por grupo, en orden de inserción
    let mut vecinos: HashMap<usize, IndexMap<usize, f64>> = HashMap::new();
    for ((a, b), w) in pesos {
        let va = vecinos.entry(*a).or_default();
        let x = va.get(b).copied().unwrap_or(0.0);
        va.insert(*b, x + w);
        let vb = vecinos.entry(*b).or_default();
        let y = vb.get(a).copied().unwrap_or(0.0);
        vb.insert(*a, y + w);
    }
    fn puntaje(vecinos: &HashMap<usize, IndexMap<usize, f64>>, grupos: &IndexMap<usize, Grupo>, a: usize, b: usize) -> f64 {
        let w = vecinos.get(&a).and_then(|m| m.get(&b)).copied().unwrap_or(0.0);
        if w <= 0.0 {
            return 0.0;
        }
        let (ga, gb) = (&grupos[&a], &grupos[&b]);
        let bono = if ga.carpetas.iter().any(|c| gb.carpetas.contains(c)) { 1.3 } else { 1.0 };
        let producto = ga.tokens.max(1) * gb.tokens.max(1);
        bono * w / (producto as f64 / 1e6).sqrt()
    }
    fn unir(vecinos: &mut HashMap<usize, IndexMap<usize, f64>>, grupos: &mut IndexMap<usize, Grupo>, a: usize, b: usize) {
        let gb = grupos.shift_remove(&b).unwrap();
        let ga = grupos.get_mut(&a).unwrap();
        ga.piezas.extend(gb.piezas);
        ga.tokens += gb.tokens;
        ga.carpetas.extend(gb.carpetas);
        let de_b = vecinos.remove(&b).unwrap_or_default();
        for (x, w) in de_b {
            vecinos.entry(x).or_default().shift_remove(&b);
            if x != a {
                let va = vecinos.entry(a).or_default();
                let p = va.get(&x).copied().unwrap_or(0.0);
                va.insert(x, p + w);
                let vx = vecinos.entry(x).or_default();
                let q = vx.get(&a).copied().unwrap_or(0.0);
                vx.insert(a, q + w);
            }
        }
        vecinos.entry(a).or_default().shift_remove(&a);
    }
    loop {
        let mut mejor = 0.0f64;
        let mut par: Option<(usize, usize)> = None;
        let claves: Vec<usize> = grupos.keys().copied().collect();
        for a in claves {
            let vs: Vec<usize> = vecinos.entry(a).or_default().keys().copied().collect();
            for b in vs {
                if b <= a || !grupos.contains_key(&b) || grupos[&a].tokens + grupos[&b].tokens > tope {
                    continue;
                }
                let p = puntaje(&vecinos, &grupos, a, b);
                if p > mejor {
                    mejor = p;
                    par = Some((a, b));
                }
            }
        }
        let Some((a, b)) = par else { break };
        unir(&mut vecinos, &mut grupos, a, b);
    }
    for (limite, por_carpeta) in [(tope as f64 * 0.5, true), (tope as f64 * 0.25, false)] {
        let mut cambio = true;
        while cambio {
            cambio = false;
            let mut chicos: Vec<usize> = grupos.keys().copied().collect();
            chicos.sort_by_key(|g| grupos[g].tokens);
            for a in chicos {
                if !grupos.contains_key(&a) || grupos[&a].tokens as f64 > limite {
                    continue;
                }
                let candidatos: Vec<usize> = grupos
                    .keys()
                    .copied()
                    .filter(|b| {
                        *b != a
                            && (!por_carpeta || grupos[b].carpetas.iter().any(|c| grupos[&a].carpetas.contains(c)))
                            && grupos[&a].tokens + grupos[b].tokens <= tope
                    })
                    .collect();
                if let Some(b) = candidatos.iter().copied().min_by_key(|b| grupos[b].tokens) {
                    unir(&mut vecinos, &mut grupos, a.min(b), a.max(b));
                    cambio = true;
                }
            }
        }
    }
    grupos.into_values().map(|g| g.piezas).collect()
}

/// `cambios_git`: cuántos de los últimos commits tocaron cada archivo.
pub fn cambios_git(raiz: &str, commits: usize) -> HashMap<String, i64> {
    let salida = Command::new("git")
        .args(["-C", raiz, "log", &format!("-{commits}"), "--format=", "--name-only"])
        .stdin(Stdio::null())
        .stderr(Stdio::null())
        .output();
    let mut cuenta: HashMap<String, i64> = HashMap::new();
    if let Ok(o) = salida {
        for linea in splitlines(&String::from_utf8_lossy(&o.stdout)) {
            let l = strip(linea);
            if !l.is_empty() {
                *cuenta.entry(l.to_string()).or_insert(0) += 1;
            }
        }
    }
    cuenta
}

/// `componentes_fuertes`: Tarjan iterativo (los vecinos en orden ascendente).
pub fn componentes_fuertes(n: usize, aristas: &IndexMap<usize, ConjuntoInt>) -> Vec<Vec<usize>> {
    let mut indice: HashMap<usize, usize> = HashMap::new();
    let mut bajo: HashMap<usize, usize> = HashMap::new();
    let mut en_pila: HashSet<usize> = HashSet::new();
    let mut pila: Vec<usize> = vec![];
    let mut salida: Vec<Vec<usize>> = vec![];
    let mut contador = 0usize;
    let ordenados = |v: usize| -> Vec<usize> {
        let mut x: Vec<usize> = aristas.get(&v).map(|s| s.iter().map(|y| y as usize).collect()).unwrap_or_default();
        x.sort();
        x
    };
    for inicio in 0..n {
        if indice.contains_key(&inicio) {
            continue;
        }
        let mut trabajo: Vec<(usize, Vec<usize>, usize)> = vec![(inicio, ordenados(inicio), 0)];
        indice.insert(inicio, contador);
        bajo.insert(inicio, contador);
        contador += 1;
        pila.push(inicio);
        en_pila.insert(inicio);
        loop {
            let Some(top) = trabajo.last_mut() else { break };
            let v = top.0;
            // el próximo hijo sin visitar (los ya visitados que siguen en la pila bajan `bajo`)
            let mut siguiente: Option<usize> = None;
            while top.2 < top.1.len() {
                let w = top.1[top.2];
                top.2 += 1;
                if !indice.contains_key(&w) {
                    siguiente = Some(w);
                    break;
                }
                if en_pila.contains(&w) {
                    let m = bajo[&v].min(indice[&w]);
                    bajo.insert(v, m);
                }
            }
            if let Some(w) = siguiente {
                indice.insert(w, contador);
                bajo.insert(w, contador);
                contador += 1;
                pila.push(w);
                en_pila.insert(w);
                let nuevos = ordenados(w);
                trabajo.push((w, nuevos, 0));
                continue;
            }
            trabajo.pop();
            if let Some((u, _, _)) = trabajo.last() {
                let m = bajo[u].min(bajo[&v]);
                bajo.insert(*u, m);
            }
            if bajo[&v] == indice[&v] {
                let mut comp = vec![];
                loop {
                    let w = pila.pop().unwrap();
                    en_pila.remove(&w);
                    comp.push(w);
                    if w == v {
                        break;
                    }
                }
                salida.push(comp);
            }
        }
    }
    salida
}

/// `ordenar`: orden de las unidades (dependencias primero; a igualdad, lo estable) y de las piezas dentro.
pub fn ordenar(unidades: &[Vec<usize>], piezas: &[Pieza], dirigidas: &IndexMap<(usize, usize), f64>, churn: &HashMap<String, i64>) -> (Vec<usize>, HashMap<usize, Vec<usize>>) {
    let de_pieza: HashMap<usize, usize> = unidades.iter().enumerate().flat_map(|(u, l)| l.iter().map(move |p| (*p, u))).collect();
    let mut usa: IndexMap<usize, ConjuntoInt> = IndexMap::new();
    for ((a, b), _) in dirigidas {
        if let (Some(ua), Some(ub)) = (de_pieza.get(a), de_pieza.get(b)) {
            if ua != ub {
                usa.entry(*ua).or_default().agregar(*ub as i64);
            }
        }
    }
    let inestable: Vec<i64> = unidades.iter().map(|l| l.iter().map(|p| *churn.get(&piezas[*p].ruta).unwrap_or(&0)).max().unwrap_or(0)).collect();
    let comps = componentes_fuertes(unidades.len(), &usa);
    let mut de_comp: HashMap<usize, usize> = HashMap::new();
    for (i, comp) in comps.iter().enumerate() {
        for u in comp {
            de_comp.insert(*u, i);
        }
    }
    // defaultdict(set): la clave nace al leerla
    let mut depende: IndexMap<usize, ConjuntoInt> = IndexMap::new();
    for (u, vs) in &usa {
        for v in vs.iter() {
            let (cu, cv) = (de_comp[u], de_comp[&(v as usize)]);
            if cu != cv {
                depende.entry(cu).or_default().agregar(cv as i64);
            }
        }
    }
    let mut pendientes: IndexMap<usize, usize> = IndexMap::new();
    for i in 0..comps.len() {
        let n = depende.entry(i).or_default().len();
        pendientes.insert(i, n);
    }
    let mut usada_por: IndexMap<usize, ConjuntoInt> = IndexMap::new();
    for (i, ds) in &depende {
        for d in ds.iter() {
            usada_por.entry(d as usize).or_default().agregar(*i as i64);
        }
    }
    let clave = |i: usize| -> (i64, String) {
        let a = comps[i].iter().map(|u| inestable[*u]).min().unwrap_or(0);
        let b = comps[i].iter().map(|u| piezas[unidades[*u][0]].ruta.clone()).min().unwrap_or_default();
        (a, b)
    };
    let mut listas: Vec<usize> = pendientes.iter().filter(|(_, n)| **n == 0).map(|(i, _)| *i).collect();
    listas.sort_by_key(|i| clave(*i));
    let mut orden_comps = vec![];
    while !listas.is_empty() {
        let i = listas.remove(0);
        orden_comps.push(i);
        let siguientes: Vec<usize> = usada_por.entry(i).or_default().iter().map(|j| j as usize).collect();
        for j in siguientes {
            let p = pendientes.get_mut(&j).unwrap();
            *p -= 1;
            if *p == 0 {
                listas.push(j);
            }
        }
        listas.sort_by_key(|i| clave(*i));
    }
    let mut orden_unidades = vec![];
    for i in orden_comps {
        let mut comp = comps[i].clone();
        comp.sort_by_key(|u| (inestable[*u], piezas[unidades[*u][0]].ruta.clone()));
        orden_unidades.extend(comp);
    }
    let mut internas: HashMap<usize, Vec<usize>> = HashMap::new();
    for (u, lista) in unidades.iter().enumerate() {
        let conjunto: HashSet<usize> = lista.iter().copied().collect();
        let mut llamada: HashMap<usize, f64> = HashMap::new();
        for ((a, b), w) in dirigidas {
            if conjunto.contains(a) && conjunto.contains(b) {
                *llamada.entry(*b).or_insert(0.0) += w;
                *llamada.entry(*a).or_insert(0.0) -= w;
            }
        }
        let mut orden = lista.clone();
        orden.sort_by(|p, q| {
            let (lp, lq) = (-llamada.get(p).copied().unwrap_or(0.0), -llamada.get(q).copied().unwrap_or(0.0));
            lp.partial_cmp(&lq)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| piezas[*p].ruta.cmp(&piezas[*q].ruta))
                .then_with(|| piezas[*p].ini.cmp(&piezas[*q].ini))
        });
        internas.insert(u, orden);
    }
    (orden_unidades, internas)
}

/// `nombre_unidad`: «backend/recursos: frio, termico».
pub fn nombre_unidad(rutas: &[String]) -> String {
    if rutas.is_empty() {
        return "(vacía)".to_string();
    }
    let comun = if rutas.len() > 1 {
        commonpath(&rutas.iter().map(|r| r.as_str()).collect::<Vec<_>>())
    } else {
        dirname(&rutas[0]).to_string()
    };
    let nombres: Vec<String> = rutas.iter().map(|r| basename(r).rsplit_once('.').map(|(a, _)| a).unwrap_or(basename(r)).to_string()).collect();
    let mut visibles = nombres.iter().take(4).cloned().collect::<Vec<_>>().join(", ");
    if nombres.len() > 4 {
        visibles.push_str(&format!(" +{}", nombres.len() - 4));
    }
    format!("{}: {visibles}", if comun.is_empty() { "." } else { &comun })
}

/// `particionar`: piezas, pesos, grupos, orden y el resumen; con `guardar`, en la tabla `unidades`.
pub fn particionar(banco: &Banco, tope: i64, guardar: bool) -> Resultado<Value> {
    let t0 = Instant::now();
    let c = banco.conectar()?;
    let archivos: Vec<(String, String, i64, Vec<u8>)> = {
        let mut st = c.prepare("SELECT ruta, lenguaje, tokens, contenido FROM archivos ORDER BY ruta").map_err(error)?;
        let v = st
            .query_map([], |f| {
                Ok((
                    f.get::<_, Option<String>>(0)?.unwrap_or_default(),
                    f.get::<_, Option<String>>(1)?.unwrap_or_default(),
                    f.get::<_, Option<i64>>(2)?.unwrap_or(0),
                    f.get::<_, Option<Vec<u8>>>(3)?.unwrap_or_default(),
                ))
            })
            .map_err(error)?
            .collect::<rusqlite::Result<Vec<_>>>()
            .map_err(error)?;
        v
    };
    let mut simbolos_por_ruta: HashMap<String, Vec<Sim>> = HashMap::new();
    {
        let mut st = c.prepare("SELECT ruta, nombre, padre, ini, fin FROM simbolos").map_err(error)?;
        let mut fs = st.query([]).map_err(error)?;
        while let Some(f) = fs.next().map_err(error)? {
            let ruta: String = f.get::<_, Option<String>>(0).map_err(error)?.unwrap_or_default();
            simbolos_por_ruta.entry(ruta).or_default().push(Sim {
                nombre: f.get::<_, Option<String>>(1).map_err(error)?.unwrap_or_default(),
                padre: f.get::<_, Option<String>>(2).map_err(error)?.unwrap_or_default(),
                ini: f.get::<_, Option<i64>>(3).map_err(error)?.unwrap_or(0),
                fin: f.get::<_, Option<i64>>(4).map_err(error)?.unwrap_or(0),
            });
        }
    }
    let mut piezas: Vec<Pieza> = vec![];
    let vacio: Vec<Sim> = vec![];
    for (ruta, lenguaje, tokens, contenido) in &archivos {
        if !es_produccion(ruta, lenguaje) {
            continue;
        }
        let texto = descomprimir(contenido);
        let lineas = splitlines(&texto);
        piezas.extend(piezas_de_archivo(ruta, &lineas, simbolos_por_ruta.get(ruta).unwrap_or(&vacio), *tokens, tope));
    }
    let mut indice: Indice = IndexMap::new();
    for (i, p) in piezas.iter().enumerate() {
        indice.entry(p.ruta.clone()).or_default().push((p.ini, p.fin, i));
    }
    let mut inicio_simbolo: HashMap<(String, String), i64> = HashMap::new();
    {
        let mut st = c.prepare("SELECT ruta, nombre, ini FROM simbolos").map_err(error)?;
        let mut fs = st.query([]).map_err(error)?;
        while let Some(f) = fs.next().map_err(error)? {
            let r: String = f.get::<_, Option<String>>(0).map_err(error)?.unwrap_or_default();
            let n: String = f.get::<_, Option<String>>(1).map_err(error)?.unwrap_or_default();
            let ini: i64 = f.get::<_, Option<i64>>(2).map_err(error)?.unwrap_or(0);
            inicio_simbolo.insert((r, n), ini);
        }
    }
    let llamadas: Vec<(String, String, String, String, i64)> = {
        let mut st = c.prepare("SELECT ruta, desde, a_ruta, a_nombre, linea FROM llamadas").map_err(error)?;
        let v = st
            .query_map([], |f| {
                Ok((
                    f.get::<_, Option<String>>(0)?.unwrap_or_default(),
                    f.get::<_, Option<String>>(1)?.unwrap_or_default(),
                    f.get::<_, Option<String>>(2)?.unwrap_or_default(),
                    f.get::<_, Option<String>>(3)?.unwrap_or_default(),
                    f.get::<_, Option<i64>>(4)?.unwrap_or(0),
                ))
            })
            .map_err(error)?
            .collect::<rusqlite::Result<Vec<_>>>()
            .map_err(error)?;
        v
    };
    let importaciones: Vec<(String, String)> = {
        let mut st = c.prepare("SELECT ruta, destino FROM importaciones").map_err(error)?;
        let v = st
            .query_map([], |f| Ok((f.get::<_, Option<String>>(0)?.unwrap_or_default(), f.get::<_, Option<String>>(1)?.unwrap_or_default())))
            .map_err(error)?
            .collect::<rusqlite::Result<Vec<_>>>()
            .map_err(error)?;
        v
    };
    drop(c);
    let grafo = Grafo { indice, inicio_simbolo, llamadas, importaciones };
    let pesos = grafo.pesos();
    let dirigidas = grafo.dirigidas();
    let grupos = agrupar(&piezas, &pesos, tope);
    let churn = cambios_git(&banco.raiz, 300);
    let (orden, internas) = ordenar(&grupos, &piezas, &dirigidas, &churn);

    let de_pieza: HashMap<usize, usize> = grupos.iter().enumerate().flat_map(|(u, l)| l.iter().map(move |p| (*p, u))).collect();
    let suma_pesos = suma(pesos.values().copied());
    let total_peso = if pesos.is_empty() || suma_pesos == 0.0 { 1.0 } else { suma_pesos };
    let cortado = suma(pesos.iter().filter(|((a, b), _)| de_pieza[a] != de_pieza[b]).map(|(_, w)| *w));
    let mut unidades: Vec<Map<String, Value>> = vec![];
    for (pos, u) in orden.iter().enumerate() {
        let lista = &internas[u];
        let mut rutas: Vec<String> = lista.iter().map(|p| piezas[*p].ruta.clone()).collect::<std::collections::BTreeSet<_>>().into_iter().collect();
        rutas.dedup();
        let mut cruce: IndexMap<usize, f64> = IndexMap::new();
        for ((a, b), w) in &pesos {
            let (da, db) = (de_pieza[a], de_pieza[b]);
            if da == *u && db != *u {
                *cruce.entry(db).or_insert(0.0) += w;
            } else if db == *u && da != *u {
                *cruce.entry(da).or_insert(0.0) += w;
            }
        }
        let mut cruces: Vec<(usize, f64)> = cruce.into_iter().collect();
        cruces.sort_by(|x, y| y.1.partial_cmp(&x.1).unwrap_or(std::cmp::Ordering::Equal));
        let vecinas: Vec<usize> = cruces.into_iter().take(6).map(|(v, _)| v).collect();
        let mut m = Map::new();
        m.insert("id".into(), Value::from(*u));
        m.insert("orden".into(), Value::from(pos));
        m.insert("tokens".into(), Value::from(lista.iter().map(|p| piezas[*p].tokens).sum::<i64>()));
        m.insert("nombre".into(), Value::from(nombre_unidad(&rutas)));
        m.insert("rutas".into(), Value::from(rutas.clone()));
        m.insert(
            "piezas".into(),
            Value::Array(lista.iter().map(|p| json!({"ruta": piezas[*p].ruta, "ini": piezas[*p].ini, "fin": piezas[*p].fin, "tokens": piezas[*p].tokens})).collect()),
        );
        m.insert("simbolos".into(), Value::from(lista.iter().flat_map(|p| piezas[*p].simbolos.clone()).collect::<Vec<_>>()));
        m.insert("vecinas".into(), Value::from(vecinas));
        m.insert("cambios_git".into(), Value::from(rutas.iter().map(|r| *churn.get(r).unwrap_or(&0)).max().unwrap_or(0)));
        unidades.push(m);
    }
    let posicion: HashMap<usize, usize> = unidades.iter().map(|x| (x["id"].as_u64().unwrap() as usize, x["orden"].as_u64().unwrap() as usize)).collect();
    for x in unidades.iter_mut() {
        let v: Vec<usize> = x["vecinas"].as_array().unwrap().iter().map(|v| posicion[&(v.as_u64().unwrap() as usize)]).collect();
        x.insert("vecinas".into(), Value::from(v));
    }
    let mut cruce_total: IndexMap<usize, IndexMap<usize, f64>> = IndexMap::new();
    for ((a, b), w) in &pesos {
        let (da, db) = (de_pieza[a], de_pieza[b]);
        if da != db {
            *cruce_total.entry(da).or_default().entry(db).or_insert(0.0) += w;
            *cruce_total.entry(db).or_default().entry(da).or_insert(0.0) += w;
        }
    }
    let coberturas: Vec<f64> = cruce_total
        .values()
        .filter(|v| !v.is_empty())
        .map(|v| {
            let mut vals: Vec<f64> = v.values().copied().collect();
            vals.sort_by(|a, b| b.partial_cmp(a).unwrap_or(std::cmp::Ordering::Equal));
            suma(vals.iter().take(6).copied()) / suma(v.values().copied())
        })
        .collect();
    let mut cuenta: IndexMap<&str, usize> = IndexMap::new();
    for p in &piezas {
        *cuenta.entry(p.ruta.as_str()).or_insert(0) += 1;
    }
    let tokens_total: i64 = unidades.iter().map(|x| x["tokens"].as_i64().unwrap()).sum();
    let mut resumen = Map::new();
    resumen.insert("unidades".into(), Value::from(unidades.len()));
    resumen.insert("piezas".into(), Value::from(piezas.len()));
    resumen.insert("tokens".into(), Value::from(tokens_total));
    resumen.insert("tokens_max".into(), Value::from(unidades.iter().map(|x| x["tokens"].as_i64().unwrap()).max().unwrap_or(0)));
    resumen.insert("tokens_media".into(), Value::from(round_entero(tokens_total as f64 / unidades.len().max(1) as f64)));
    resumen.insert("archivos_partidos".into(), Value::from(cuenta.values().filter(|n| **n > 1).count()));
    let num = |x: f64| serde_json::Number::from_f64(x).map(Value::Number).unwrap_or(Value::Null);
    resumen.insert("peso_cortado".into(), num(round(cortado / total_peso, 3)));
    if coberturas.is_empty() {
        resumen.insert("cobertura_vecinas".into(), num(1.0));
        resumen.insert("cobertura_vecinas_min".into(), num(1.0));
    } else {
        resumen.insert("cobertura_vecinas".into(), num(round(suma(coberturas.iter().copied()) / coberturas.len() as f64, 3)));
        resumen.insert("cobertura_vecinas_min".into(), num(round(coberturas.iter().copied().fold(f64::INFINITY, f64::min), 3)));
    }
    resumen.insert("tope".into(), Value::from(tope));
    resumen.insert("segundos".into(), num(round(t0.elapsed().as_secs_f64(), 2)));
    let unidades: Vec<Value> = unidades.into_iter().map(Value::Object).collect();
    if guardar {
        banco.guardar_particion(&unidades, &resumen)?;
    }
    Ok(json!({"resumen": Value::Object(resumen), "unidades": unidades}))
}
