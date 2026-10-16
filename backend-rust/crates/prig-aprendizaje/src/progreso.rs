//! El avance del alumno en un sitio (`progreso.resumen`): el historial de desafíos, el dominio por concepto (resueltos
//! con pruebas, menos pistas y olvido), la actividad por día y la racha, las rutas de aprendizaje guiado con sus
//! bloques, qué hacer ahora, los ejercicios, lo leído en Kaggle y la biblioteca.

use crate::desafios::{self, clave};
use crate::{dataset, planes, telemetria};
use prig_plataforma::valor::{redondear, Mapa, Valor};
use std::path::Path;

// ---------------------------------------------------------------------------------------------- fechas

/// Días desde el 1/1/1970 de una fecha civil
fn dias_civiles(a: i64, m: i64, d: i64) -> i64 {
    let a = if m <= 2 { a - 1 } else { a };
    let era = if a >= 0 { a } else { a - 399 } / 400;
    let ae = a - era * 400;
    let md = (m + 9) % 12;
    let dda = (153 * md + 2) / 5 + d - 1;
    let ddr = ae * 365 + ae / 4 - ae / 100 + dda;
    era * 146097 + ddr - 719468
}

fn civil(z: i64) -> (i64, i64, i64) {
    let z = z + 719468;
    let era = if z >= 0 { z } else { z - 146096 } / 146097;
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    (if m <= 2 { y + 1 } else { y }, m, d)
}

fn iso(z: i64) -> String {
    let (a, m, d) = civil(z);
    format!("{a:04}-{m:02}-{d:02}")
}

/// `date.fromisoformat` de «AAAA-MM-DD» (None si no es una fecha válida)
fn dia_de(t: &str) -> Option<i64> {
    let d = dataset::dia_iso(t)?;
    if d.len() != t.len() && !t.contains('T') && !t.contains(' ') {
        return None;
    }
    Some(dias_civiles(d[..4].parse().ok()?, d[5..7].parse().ok()?, d[8..10].parse().ok()?))
}

fn hoy() -> i64 {
    let h = prig_plataforma::py::ahora_iso();
    dias_civiles(h[..4].parse().unwrap_or(1970), h[5..7].parse().unwrap_or(1), h[8..10].parse().unwrap_or(1))
}

/// `_dias_desde(valor)`
fn dias_desde(v: &Valor) -> Option<i64> {
    match v {
        Valor::Texto(t) if !t.is_empty() => dia_de(t).map(|d| hoy() - d),
        _ => None,
    }
}

fn s(v: &Valor) -> String {
    v.texto_py()
}

fn n(v: Option<&Valor>) -> i64 {
    v.and_then(|x| x.num()).unwrap_or(0.0) as i64
}

// ---------------------------------------------------------------------------------------------- conceptos

/// `_dominio(vistos, resueltos, pistas, dias)`
fn dominio(vistos: i64, resueltos: i64, pistas: i64, dias: Option<i64>) -> i64 {
    if vistos == 0 {
        return 0;
    }
    let mut v = 100.0 * resueltos as f64 / vistos as f64;
    v -= 8.0 * (pistas as f64 / vistos as f64);
    if let Some(d) = dias {
        v -= (d.div_euclid(7)).min(20) as f64;
    }
    (v.round_ties_even() as i64).clamp(0, 100)
}

/// `conceptos(filas)`: el dominio de cada concepto (solo lo comprobado con pruebas)
pub fn conceptos(filas: &[Mapa]) -> Vec<Mapa> {
    let mut grupos: Vec<(String, Mapa, Vec<Valor>)> = Vec::new();
    for f in filas {
        if !f.verdad("verificable") {
            continue;
        }
        let lista: Vec<Valor> = match f.get("conceptos") {
            Some(Valor::Lista(l)) if !l.is_empty() => l.clone(),
            _ => vec![match f.get("titulo") {
                Some(t) if t.verdad() => t.clone(),
                _ => Valor::Texto("general".into()),
            }],
        };
        for c in lista.into_iter().take(4) {
            let k = clave(&s(&c));
            let i = match grupos.iter().position(|g| g.0 == k) {
                Some(i) => i,
                None => {
                    grupos.push((
                        k,
                        Mapa::new()
                            .con("concepto", c.clone())
                            .con("vistos", 0)
                            .con("resueltos", 0)
                            .con("rendidos", 0)
                            .con("intentos", 0)
                            .con("pistas", 0)
                            .con("ultima", Valor::Nulo),
                        Vec::new(),
                    ));
                    grupos.len() - 1
                }
            };
            let g = &mut grupos[i];
            let sumar = |m: &mut Mapa, k: &str, x: i64| {
                let v = n(m.get(k)) + x;
                m.poner(k, v as i128);
            };
            sumar(&mut g.1, "vistos", 1);
            sumar(&mut g.1, "resueltos", (f.texto("estado") == Some("resuelto")) as i64);
            sumar(&mut g.1, "rendidos", (f.texto("estado") == Some("rendido")) as i64);
            sumar(&mut g.1, "intentos", n(f.get("intentos")));
            sumar(&mut g.1, "pistas", n(f.get("pistas")));
            g.2.push(f.valor("id").clone());
            let actualizado = f.get("actualizado").filter(|v| v.verdad()).map(s).unwrap_or_default();
            let ultima = g.1.get("ultima").filter(|v| v.verdad()).map(s).unwrap_or_default();
            if actualizado > ultima {
                g.1.poner("ultima", f.valor("actualizado").clone());
            }
        }
    }
    let mut salida: Vec<Mapa> = grupos
        .into_iter()
        .map(|(_, mut g, ids)| {
            let d = dominio(n(g.get("vistos")), n(g.get("resueltos")), n(g.get("pistas")), dias_desde(g.valor("ultima")));
            g.poner("desafios", Valor::Lista(ids.into_iter().take(20).collect()));
            g.poner("dominio", d as i128);
            g
        })
        .collect();
    salida.sort_by_key(|g| (n(g.get("dominio")), -n(g.get("vistos"))));
    salida
}

// ---------------------------------------------------------------------------------------------- actividad y racha

/// `actividad(filas, almacen, telemetria, dias)`: acciones de aprendizaje por día
fn actividad(filas: &[Mapa], dir: &Path, espacio: Option<&Path>, dias: i64) -> Result<Vec<(String, i64)>, ()> {
    let desde = iso(hoy() - dias);
    let mut cuenta: Vec<(String, i64)> = Vec::new();
    let mut sumar = |dia: String| match cuenta.iter_mut().find(|x| x.0 == dia) {
        Some(x) => x.1 += 1,
        None => cuenta.push((dia, 1)),
    };
    let prefijo = |v: &Valor| -> String { s(v).chars().take(10).collect() };
    for f in filas {
        let Ok(Valor::Mapa(d)) = desafios::obtener(dir, &s(f.valor("id"))) else { continue };
        let hist = match d.get("progreso") {
            Some(Valor::Mapa(p)) => match p.get("historial") {
                Some(Valor::Lista(l)) => l.clone(),
                Some(v) if v.verdad() => return Err(()),
                _ => Vec::new(),
            },
            Some(v) if v.verdad() => return Err(()),
            _ => Vec::new(),
        };
        for h in hist {
            let Valor::Mapa(h) = h else { return Err(()) };
            let dia = prefijo(h.get("cuando").unwrap_or(&Valor::Texto(String::new())));
            if dia >= desde {
                sumar(dia);
            }
        }
        let creado = match d.get("creado") {
            Some(v) if v.verdad() => prefijo(v),
            _ => String::new(),
        };
        if creado >= desde {
            sumar(creado);
        }
    }
    if let Some(Ok(c)) = espacio.map(telemetria::abrir) {
        if let Ok(mut st) = c.prepare("SELECT created_at FROM exercise_events WHERE event_type='submission' AND created_at >= ?1;") {
            if let Ok(filas) = st.query_map([&desde], |r| r.get::<_, rusqlite::types::Value>(0)) {
                for v in filas.flatten() {
                    let t = match v {
                        rusqlite::types::Value::Text(t) => t,
                        rusqlite::types::Value::Integer(i) => i.to_string(),
                        rusqlite::types::Value::Real(x) => prig_plataforma::valor::repr_real(x),
                        rusqlite::types::Value::Null => "None".into(),
                        rusqlite::types::Value::Blob(_) => continue,
                    };
                    sumar(t.chars().take(10).collect());
                }
            }
        }
    }
    cuenta.sort();
    Ok(cuenta)
}

/// `racha(dias_activos)`: días seguidos con actividad (hasta hoy o ayer), la mejor y cuántos
fn racha(dias: &[(String, i64)]) -> Result<Mapa, ()> {
    let mut fechas: Vec<&String> = dias.iter().filter(|x| x.1 != 0).map(|x| &x.0).collect();
    fechas.sort();
    fechas.dedup();
    let esta = |d: i64| fechas.iter().any(|f| **f == iso(d));
    let h = hoy();
    let mut actual = 0;
    if esta(h) || esta(h - 1) {
        let mut cursor = if esta(h) { h } else { h - 1 };
        while esta(cursor) {
            actual += 1;
            cursor -= 1;
        }
    }
    let (mut mejor, mut seguidos) = (0, 0);
    let mut anterior: Option<i64> = None;
    for d in &fechas {
        let f = dia_de(d).filter(|_| d.len() == 10).ok_or(())?;
        seguidos = if anterior.is_some_and(|a| f - a == 1) { seguidos + 1 } else { 1 };
        mejor = mejor.max(seguidos);
        anterior = Some(f);
    }
    Ok(Mapa::new().con("actual", actual as i128).con("mejor", mejor as i128).con("dias_activos", fechas.len() as i128))
}

// ---------------------------------------------------------------------------------------------- rutas y siguientes

/// Los ids de las rutas guiadas en el orden de `list_paths` (lo creado más reciente primero, sin repetir)
fn ids_de_rutas(espacio: &Path) -> Vec<String> {
    let mut ids: Vec<Valor> = Vec::new();
    let mut resumenes: Vec<Mapa> = Vec::new();
    for r in planes::listar_seguimientos(espacio) {
        let id = r.valor("id").clone();
        match ids.iter().position(|x| *x == id) {
            Some(i) => resumenes[i] = r,
            None => {
                ids.push(id);
                resumenes.push(r);
            }
        }
    }
    planes::ordenar_desc(&mut resumenes, "created_at");
    resumenes.iter().map(|r| s(r.valor("id"))).collect()
}

/// `rutas(filas, guided)`: cada ruta con sus bloques y los desafíos que salieron de cada uno. Una ruta que no se puede
/// leer se salta (antes tumbaba el resumen entero)
fn rutas(filas: &[Mapa], espacio: &Path) -> Vec<Mapa> {
    let mut salida = Vec::new();
    for id in ids_de_rutas(espacio) {
        let ruta = match planes::cargar_seguimiento(espacio, &id) {
            Ok(Some(r)) => r,
            Ok(None) => continue,
            Err(e) => {
                eprintln!("⚠️ Ruta {id} omitida del progreso: {e}");
                continue;
            }
        };
        let rid = s(ruta.valor("id"));
        let hechos: Vec<String> = ruta.lista("completed_blocks").unwrap_or(&[]).iter().map(s).collect();
        let mut bloques = Vec::new();
        let mut ids_bloques = Vec::new();
        for b in ruta.lista("blocks").unwrap_or(&[]) {
            let Valor::Mapa(b) = b else { continue };
            let bid = s(b.valor("block_id"));
            ids_bloques.push(bid.clone());
            let desafios: Vec<&Mapa> = filas
                .iter()
                .filter(|f| f.get("bloque_id").is_some_and(|v| v.verdad()) && format!("{}:{}", s(f.valor("ruta_id")), s(f.valor("bloque_id"))) == format!("{rid}:{bid}"))
                .collect();
            bloques.push(
                Mapa::new()
                    .con("id", bid.clone())
                    .con("titulo", b.valor("title").clone())
                    .con("temas", b.get("topics").cloned().unwrap_or(Valor::Lista(vec![])))
                    .con("completado", hechos.contains(&bid))
                    .con("desafios", desafios.len() as i128)
                    .con("resueltos", desafios.iter().filter(|d| d.texto("estado") == Some("resuelto")).count() as i128),
            );
        }
        let mut unicos = hechos.clone();
        unicos.sort();
        unicos.dedup();
        let completados = unicos.iter().filter(|h| ids_bloques.contains(h)).count();
        let con_desafio = bloques.iter().filter(|b| n(b.get("desafios")) > 0).count();
        salida.push(
            Mapa::new()
                .con("id", rid)
                .con("meta", ruta.valor("goal").clone())
                .con("nivel", ruta.valor("level").clone())
                .con("total", bloques.len() as i128)
                .con("bloques", Valor::Nulo)
                .con("completados", completados as i128)
                .con("con_desafio", con_desafio as i128),
        );
        let ultima = salida.last_mut().unwrap();
        // el orden de Python: id, meta, nivel, bloques, total, completados, con_desafio
        let mut m = Mapa::new();
        for k in ["id", "meta", "nivel"] {
            m.poner(k, ultima.valor(k).clone());
        }
        m.poner("bloques", Valor::Lista(bloques.into_iter().map(Valor::Mapa).collect()));
        for k in ["total", "completados", "con_desafio"] {
            m.poner(k, ultima.valor(k).clone());
        }
        *ultima = m;
    }
    salida
}

/// `siguientes(filas, conceptos, rutas)`: qué hacer ahora, sin pedírselo a ningún modelo
fn siguientes(filas: &[Mapa], lista_conceptos: &[Mapa], lista_rutas: &[Mapa]) -> Vec<Mapa> {
    let mut pasos = Vec::new();
    let mut vistos = Vec::new();
    for f in filas {
        let titulo = f.get("titulo").filter(|v| v.verdad()).map(s).unwrap_or_default();
        if f.texto("estado") == Some("en_curso") && !vistos.contains(&clave(&titulo)) {
            vistos.push(clave(&titulo));
            let mejor = f.mapa("mejor").cloned().unwrap_or_default();
            let total = mejor.get("total").cloned().unwrap_or(Valor::Nulo);
            let extra = if total.verdad() { format!(" ({}/{} pruebas)", s(mejor.valor("pasados")), s(&total)) } else { String::new() };
            pasos.push(
                Mapa::new()
                    .con("tipo", "retomar")
                    .con("texto", format!("Sigue «{}», lo dejaste a medias{extra}", s(f.valor("titulo"))))
                    .con("desafio_id", f.valor("id").clone()),
            );
        }
        if pasos.len() >= 2 {
            break;
        }
    }
    for c in lista_conceptos {
        let (dom, rend, pis, vis, res) = (n(c.get("dominio")), n(c.get("rendidos")), n(c.get("pistas")), n(c.get("vistos")), n(c.get("resueltos")));
        if dom < 60 && (rend != 0 || pis != 0 || vis > res) {
            let extra = if rend != 0 { format!(", {rend} visto con solución") } else { String::new() };
            pasos.push(
                Mapa::new()
                    .con("tipo", "practicar")
                    .con("texto", format!("Refuerza «{}»: dominio {dom}/100{extra}", s(c.valor("concepto"))))
                    .con("tema", c.valor("concepto").clone()),
            );
        }
        if pasos.len() >= 5 {
            break;
        }
    }
    for r in lista_rutas {
        let pendiente = r.lista("bloques").unwrap_or(&[]).iter().find_map(|b| match b {
            Valor::Mapa(b) if !b.verdad("completado") => Some(b.clone()),
            _ => None,
        });
        if let Some(b) = pendiente {
            let mut tema = vec![s(b.valor("titulo"))];
            tema.extend(b.lista("temas").unwrap_or(&[]).iter().take(3).map(s));
            pasos.push(
                Mapa::new()
                    .con("tipo", "bloque")
                    .con(
                        "texto",
                        format!("Bloque «{}» de «{}»{}", s(b.valor("titulo")), s(r.valor("meta")), if n(b.get("desafios")) == 0 { " (sin desafíos todavía)" } else { "" }),
                    )
                    .con("ruta_id", r.valor("id").clone())
                    .con("bloque_id", b.valor("id").clone())
                    .con("tema", tema.join(", ")),
            );
        }
        if pasos.len() >= 7 {
            break;
        }
    }
    pasos.truncate(7);
    pasos
}

/// `dataset.get_dataset()`: el guardado (migrado y con la forma del modelo) o, si no vale, uno nuevo
fn temas_dominados(espacio: &Path) -> usize {
    let ruta = espacio.join(".prig_dataset/user_learning_dataset.json");
    if ruta.exists() {
        if let Ok(d) = planes::cargar_migrado(&ruta, "dataset") {
            if let Some(Valor::Lista(l)) = d.get("mastered_topics") {
                if l.iter().all(|x| matches!(x, Valor::Mapa(_))) {
                    return l.len();
                }
            } else if d.get("mastered_topics").is_none() {
                return 0;
            }
        }
    }
    dataset::construir(espacio).ok().and_then(|d| d.lista("mastered_topics").map(|l| l.len())).unwrap_or(0)
}

/// `progreso.resumen(almacen, guided, telemetria, dataset, dias, kaggle)`; `lecturas` es `kaggle_lector.resumen_lecturas()`.
/// Sin `espacio`, como `progreso.resumen(almacen)`: sin rutas, telemetría ni dataset
pub fn resumen(dir: &Path, espacio: Option<&Path>, dias: i64, lecturas: Vec<Mapa>) -> Result<Mapa, ()> {
    let filas = desafios::historial(dir, None, None, None, desafios::MAX_HISTORIAL as i64)?;
    let lista_conceptos = conceptos(&filas);
    let activos = actividad(&filas, dir, espacio, dias)?;
    let lista_rutas = espacio.map(|e| rutas(&filas, e)).unwrap_or_default();

    let resueltos: Vec<&Mapa> = filas.iter().filter(|f| f.texto("estado") == Some("resuelto")).collect();
    let tiempos: Vec<f64> = resueltos.iter().filter_map(|f| f.get("segundos").filter(|v| v.verdad()).and_then(|v| v.num())).collect();
    let mut por_estado = Mapa::new();
    let mut por_fuente = Mapa::new();
    for f in &filas {
        let e = s(f.valor("estado"));
        por_estado.poner(e.clone(), (n(por_estado.get(&e)) + 1) as i128);
        let fu = f.get("fuente").filter(|v| v.verdad()).map(s).unwrap_or_else(|| "modelo".into());
        por_fuente.poner(fu.clone(), (n(por_fuente.get(&fu)) + 1) as i128);
    }
    // leer una clave de un `defaultdict(int)` la crea: el detalle de abajo añade «en_curso» y «rendido» con 0
    for k in ["en_curso", "rendido"] {
        if !por_estado.contiene(k) {
            por_estado.poner(k, 0);
        }
    }
    let mut actividades = vec![Valor::Mapa(
        Mapa::new()
            .con("id", "desafios")
            .con("nombre", "Desafíos")
            .con("hechos", resueltos.len() as i128)
            .con("total", filas.len() as i128)
            .con("detalle", format!("{} en curso · {} vistos con solución", n(por_estado.get("en_curso")), n(por_estado.get("rendido")))),
    )];
    if !lista_rutas.is_empty() {
        let suma = |k: &str| lista_rutas.iter().map(|r| n(r.get(k))).sum::<i64>();
        actividades.push(Valor::Mapa(
            Mapa::new()
                .con("id", "plan")
                .con("nombre", "Plan de estudios")
                .con("hechos", suma("completados") as i128)
                .con("total", suma("total") as i128)
                .con("detalle", format!("{} ruta(s) · {} bloques con desafíos", lista_rutas.len(), suma("con_desafio"))),
        ));
    }
    if let Some(Ok(m)) = espacio.map(|e| telemetria::abrir(e).and_then(|c| telemetria::metricas(&c, dias))) {
        if m.verdad("submissions") {
            let intentados = m.get("exercises_attempted").cloned().unwrap_or(Valor::Entero(0));
            actividades.push(Valor::Mapa(
                Mapa::new()
                    .con("id", "ejercicios")
                    .con("nombre", "Ejercicios y retos")
                    .con("hechos", intentados.clone())
                    .con("total", intentados)
                    .con("detalle", format!("{} entregas · {}% resueltos", s(m.valor("submissions")), m.get("solve_rate").map(s).unwrap_or_else(|| "None".into()))),
            ));
        }
    }
    if !lecturas.is_empty() {
        let leidas: i64 = lecturas.iter().map(|l| n(l.get("leidas"))).sum();
        let total: i64 = lecturas.iter().map(|l| n(l.get("total"))).sum();
        let enteros = lecturas.iter().filter(|l| n(l.get("total")) != 0 && n(l.get("leidas")) >= n(l.get("total"))).count();
        actividades.push(Valor::Mapa(
            Mapa::new()
                .con("id", "kaggle")
                .con("nombre", "Notebooks de Kaggle")
                .con("hechos", leidas as i128)
                .con("total", total as i128)
                .con("detalle", format!("{} notebook(s) · {enteros} leídos enteros", lecturas.len())),
        ));
    }
    let dominados = espacio.map(temas_dominados).unwrap_or(0);
    if dominados > 0 {
        actividades.push(Valor::Mapa(
            Mapa::new()
                .con("id", "biblioteca")
                .con("nombre", "Biblioteca")
                .con("hechos", dominados as i128)
                .con("total", dominados as i128)
                .con("detalle", format!("{dominados} temas marcados como dominados")),
        ));
    }
    let suma_intentos: i64 = resueltos.iter().map(|f| n(f.get("intentos"))).sum();
    let desafios_m = Mapa::new()
        .con("total", filas.len() as i128)
        .con("por_estado", por_estado)
        .con("por_fuente", por_fuente)
        .con("resueltos_sin_pistas", resueltos.iter().filter(|f| !f.verdad("pistas")).count() as i128)
        .con("con_razonamiento", filas.iter().filter(|f| f.verdad("pasos_razonamiento")).count() as i128)
        .con("con_plan", filas.iter().filter(|f| f.verdad("plan_escrito")).count() as i128)
        .con("minutos", if tiempos.is_empty() { 0 } else { (tiempos.iter().sum::<f64>() / 60.0).round_ties_even() as i128 })
        .con(
            "media_intentos",
            if resueltos.is_empty() { Valor::Nulo } else { Valor::Real(redondear(suma_intentos as f64 / resueltos.len() as f64, 1)) },
        );
    let fuertes: Vec<Valor> = lista_conceptos.iter().rev().filter(|c| n(c.get("dominio")) >= 70).take(5).cloned().map(Valor::Mapa).collect();
    let flojos: Vec<Valor> = lista_conceptos.iter().filter(|c| n(c.get("dominio")) < 60).take(5).cloned().map(Valor::Mapa).collect();
    let racha_m = racha(&activos)?;
    let mut pasos: Vec<Valor> = siguientes(&filas, &lista_conceptos, &lista_rutas).into_iter().map(Valor::Mapa).collect();
    pasos.extend(
        lecturas
            .iter()
            .filter(|l| n(l.get("total")) != 0 && n(l.get("leidas")) < n(l.get("total")))
            .take(2)
            .map(|l| {
                Valor::Mapa(
                    Mapa::new()
                        .con("tipo", "kaggle")
                        .con("texto", format!("Sigue leyendo «{}» ({}/{} celdas)", s(l.valor("titulo")), s(l.valor("leidas")), s(l.valor("total"))))
                        .con("ref", l.valor("ref").clone())
                        .con("celda", l.get("ultima_celda").cloned().unwrap_or(Valor::Nulo)),
                )
            }),
    );
    Ok(Mapa::new()
        .con("desafios", desafios_m)
        .con("actividades", Valor::Lista(actividades))
        .con("conceptos", Valor::Lista(lista_conceptos.iter().cloned().map(Valor::Mapa).collect()))
        .con("fuertes", Valor::Lista(fuertes))
        .con("flojos", Valor::Lista(flojos))
        .con("actividad", Mapa::from_iter_pares(activos.into_iter().map(|(k, v)| (k, Valor::Entero(v as i128)))))
        .con("racha", racha_m)
        .con("rutas", Valor::Lista(lista_rutas.into_iter().map(Valor::Mapa).collect()))
        .con("siguientes", Valor::Lista(pasos))
        .con("kaggle", Valor::Lista(lecturas.into_iter().take(10).map(Valor::Mapa).collect()))
        .con("ultimos", Valor::Lista(filas.into_iter().take(8).map(Valor::Mapa).collect()))
        .con("generado", prig_plataforma::py::ahora_iso().chars().take(19).collect::<String>()))
}

trait DesdePares {
    fn from_iter_pares(it: impl Iterator<Item = (String, Valor)>) -> Mapa;
}

impl DesdePares for Mapa {
    fn from_iter_pares(it: impl Iterator<Item = (String, Valor)>) -> Mapa {
        let mut m = Mapa::new();
        for (k, v) in it {
            m.poner(k, v);
        }
        m
    }
}

#[cfg(test)]
mod pruebas {
    use super::*;

    #[test]
    fn fechas_y_dominio() {
        assert_eq!(iso(dias_civiles(2026, 10, 15)), "2026-10-15");
        assert_eq!(iso(dias_civiles(2024, 3, 1) - 1), "2024-02-29");
        assert_eq!(dominio(4, 3, 2, Some(15)), 69);
        assert_eq!(dominio(0, 0, 0, None), 0);
    }
}
