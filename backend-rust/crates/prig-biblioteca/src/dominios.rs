//! La taxonomía de dominios (`kaggle_worker/domains.py`), leída de `backend/catalogos/dominios.json` (la copia que
//! vigila `test_dominios_json.py`): los dominios con sus palabras clave, sus dependencias, los puentes conocidos y
//! proponer el dominio de un libro por su título y su texto.

use std::sync::OnceLock;

use prig_recursos::valor::{Mapa, Valor};

fn lista(v: &Valor) -> &[Valor] {
    match v {
        Valor::Lista(l) => l,
        _ => &[],
    }
}
use unicode_general_category::{get_general_category, GeneralCategory};
use unicode_normalization::UnicodeNormalization;

fn datos() -> &'static Mapa {
    static D: OnceLock<Mapa> = OnceLock::new();
    D.get_or_init(|| match prig_plataforma::json::leer(include_str!("../../../../backend/catalogos/dominios.json")) {
        Ok(Valor::Mapa(m)) => m,
        _ => Mapa::new(),
    })
}

/// `DOMAINS`
pub fn dominios() -> &'static Mapa {
    static D: OnceLock<Mapa> = OnceLock::new();
    D.get_or_init(|| datos().mapa("DOMAINS").cloned().unwrap_or_default())
}

pub fn es_dominio(d: &str) -> bool {
    dominios().contiene(d)
}

/// `KNOWN_BRIDGES`: nombre → dominios
pub fn puentes_conocidos() -> Vec<(String, Vec<String>)> {
    datos()
        .mapa("KNOWN_BRIDGES")
        .map(|m| m.iter().map(|(k, v)| (k.clone(), lista(v).iter().map(Valor::texto_py).collect())).collect())
        .unwrap_or_default()
}

fn aristas() -> Vec<(String, String)> {
    datos()
        .lista("DOMAIN_EDGES")
        .unwrap_or(&[])
        .iter()
        .filter_map(|e| {
            let l = lista(e);
            Some((l.first()?.texto_py(), l.get(1)?.texto_py()))
        })
        .collect()
}

/// `dominios_relacionados`
pub fn relacionados(d: &str) -> Vec<String> {
    let mut v: Vec<String> = aristas().into_iter().filter_map(|(a, b)| if a == d { Some(b) } else if b == d { Some(a) } else { None }).collect();
    v.sort();
    v.dedup();
    v
}

/// `distancia_dominios`: saltos en el grafo (0 mismo, 99 si no se llega)
pub fn distancia(a: &str, b: &str) -> i64 {
    if a == b {
        return 0;
    }
    let mut visitados = vec![a.to_string()];
    let mut frontera = vec![a.to_string()];
    let mut saltos = 0;
    while !frontera.is_empty() && saltos < 4 {
        saltos += 1;
        let mut siguiente = Vec::new();
        for n in &frontera {
            for v in relacionados(n) {
                if v == b {
                    return saltos;
                }
                if !visitados.contains(&v) {
                    visitados.push(v.clone());
                    siguiente.push(v);
                }
            }
        }
        frontera = siguiente;
    }
    99
}

/// `_normalizar`: minúsculas, sin acentos, separadores a espacios
pub fn normalizar(t: &str) -> String {
    static R: OnceLock<(regex::Regex, regex::Regex)> = OnceLock::new();
    let (sep, esp) = R.get_or_init(|| (regex::Regex::new(r"[_\-./]+").unwrap(), regex::Regex::new(r"\s+").unwrap()));
    let t: String = t.to_lowercase().nfd().filter(|c| get_general_category(*c) != GeneralCategory::NonspacingMark).collect();
    let t = sep.replace_all(&t, " ");
    prig_plataforma::py::strip(&esp.replace_all(&t, " ")).to_string()
}

/// `_casa`: la clave en el texto, tolerando plurales
fn casa(clave: &str, blob: &str) -> bool {
    let clave = normalizar(clave);
    if blob.contains(&clave) {
        return true;
    }
    let partes: Vec<&str> = clave.split_whitespace().collect();
    if partes.is_empty() {
        return false;
    }
    let patron = partes.iter().map(|p| format!("{}(?:es|s)?", regex::escape(p))).collect::<Vec<_>>().join(r"\s+");
    regex::Regex::new(&patron).map(|r| r.is_match(blob)).unwrap_or(false)
}

/// `puntuar_dominios`: el título pesa 5, el texto (8.000 caracteres) 1
pub fn puntuar(texto: &str, nombre: &str) -> Vec<(String, i64)> {
    let titulo = normalizar(nombre);
    let cuerpo = normalizar(&texto.chars().take(8000).collect::<String>());
    dominios()
        .iter()
        .map(|(d, info)| {
            let claves: Vec<String> = match info {
                Valor::Mapa(m) => m.lista("keywords").unwrap_or(&[]).iter().map(Valor::texto_py).collect(),
                _ => Vec::new(),
            };
            let t = claves.iter().filter(|k| casa(k, &titulo)).count() as i64;
            let c = claves.iter().filter(|k| casa(k, &cuerpo)).count() as i64;
            (d.clone(), t * 5 + c)
        })
        .collect()
}

/// `sugerir_dominio`
pub fn sugerir(texto: &str, nombre: &str) -> String {
    let p = puntuar(texto, nombre);
    // `max(puntos, key=puntos.get)`: el primero con la puntuación más alta
    let mut mejor: Option<&(String, i64)> = None;
    for x in &p {
        if mejor.is_none_or(|m| x.1 > m.1) {
            mejor = Some(x);
        }
    }
    match mejor {
        Some((d, n)) if *n > 0 => d.clone(),
        _ => "machine_learning".into(),
    }
}

/// `sugerir_dominio_con_confianza`
pub fn sugerir_con_confianza(texto: &str, nombre: &str) -> Mapa {
    let mut orden = puntuar(texto, nombre);
    orden.sort_by_key(|(_, n)| -n);
    let (mejor, punto) = orden[0].clone();
    let segundo = orden.get(1).map(|x| x.1).unwrap_or(0);
    if punto == 0 {
        return Mapa::new().con("dominio", "machine_learning").con("puntos", 0).con("seguro", false).con("motivo", "ninguna palabra clave coincide; es solo el valor por defecto");
    }
    if punto - segundo < 2 {
        return Mapa::new()
            .con("dominio", mejor)
            .con("puntos", punto)
            .con("seguro", false)
            .con("motivo", format!("muy parejo con {} ({punto} vs {segundo})", orden[1].0));
    }
    Mapa::new().con("dominio", mejor).con("puntos", punto).con("seguro", true).con("motivo", "")
}
