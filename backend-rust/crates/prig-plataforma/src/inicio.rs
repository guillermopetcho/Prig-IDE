//! La pantalla de inicio (`inicio.py`): el perfil editable (`~/.prig_inicio.json` o `PRIG_INICIO_ARCHIVO`), la línea
//! de actividad reciente y la tira de la semana. Juntar los bloques (`resumen`) sigue en Python mientras las fuentes
//! (progreso, Kaggle, modelos) sean objetos de Python.

use crate::py::{self, get_py, ErrorPy};
use crate::valor::{Mapa, Valor};
use std::path::Path;

pub const NIVELES: [&str; 3] = ["principiante", "intermedio", "avanzado"];

type R<T> = Result<T, ErrorPy>;

pub fn por_defecto() -> Mapa {
    Mapa::new()
        .con("nombre", "")
        .con("objetivo", "")
        .con("nivel", "principiante")
        .con("mostrar_al_abrir", true)
        .con(
            "favoritas",
            Valor::Lista(["herr.practica", "herr.kaggle", "herr.github", "herr.guiado"].iter().map(|s| Valor::from(*s)).collect()),
        )
}

pub fn ruta_perfil() -> String {
    match std::env::var("PRIG_INICIO_ARCHIVO") {
        Ok(r) if !r.is_empty() => r,
        _ => py::expanduser("~/.prig_inicio.json"),
    }
}

/// `perfil()`: lo guardado sobre lo de por defecto (solo las claves conocidas)
pub fn perfil() -> R<Mapa> {
    let ruta = ruta_perfil();
    let datos = match std::fs::read(&ruta) {
        Ok(b) => match String::from_utf8(b) {
            Ok(t) => crate::json::leer(&t).unwrap_or_else(|_| Valor::Mapa(Mapa::new())),
            Err(_) => Valor::Mapa(Mapa::new()),
        },
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Valor::Mapa(Mapa::new()),
        Err(e) => return Err(ErrorPy::os(&e, &ruta)),
    };
    let Valor::Mapa(datos) = datos else {
        return Err(ErrorPy::Atributo(format!("'{}' object has no attribute 'items'", py::tipo(&datos))));
    };
    let mut p = por_defecto();
    for (k, v) in datos.iter() {
        if p.contiene(k) {
            p.poner(k.clone(), v.clone());
        }
    }
    Ok(p)
}

fn cortar(t: &str, n: usize) -> String {
    t.chars().take(n).collect()
}

/// `str(v or "")`
fn texto_o_vacio(v: &Valor) -> String {
    if v.verdad() {
        v.texto_py()
    } else {
        String::new()
    }
}

/// `guardar_perfil(cambios)`
pub fn guardar_perfil(cambios: &Mapa) -> R<Mapa> {
    let mut actual = perfil()?;
    if let Some(n) = cambios.get("nombre") {
        let t = texto_o_vacio(n);
        // re.sub(r"\s+", " ", ...).strip()
        let mut limpio = String::with_capacity(t.len());
        let mut blanco = false;
        for c in t.chars() {
            if c.is_whitespace() || ('\x1c'..='\x1f').contains(&c) {
                if !blanco {
                    limpio.push(' ');
                }
                blanco = true;
            } else {
                limpio.push(c);
                blanco = false;
            }
        }
        actual.poner("nombre", cortar(py::strip(&limpio), 60));
    }
    if let Some(o) = cambios.get("objetivo") {
        actual.poner("objetivo", cortar(py::strip(&texto_o_vacio(o)), 300));
    }
    if let Some(Valor::Texto(n)) = cambios.get("nivel") {
        if NIVELES.contains(&n.as_str()) {
            actual.poner("nivel", n.clone());
        }
    }
    if let Some(m) = cambios.get("mostrar_al_abrir") {
        actual.poner("mostrar_al_abrir", m.verdad());
    }
    if let Some(Valor::Lista(f)) = cambios.get("favoritas") {
        actual.poner("favoritas", Valor::Lista(f.iter().take(12).map(|x| Valor::Texto(cortar(&x.texto_py(), 60))).collect()));
    }
    let ruta = ruta_perfil();
    let dir = py::dirname(&ruta);
    py::makedirs_py(if dir.is_empty() { "." } else { &dir })?;
    let tmp = format!("{ruta}.tmp");
    std::fs::write(&tmp, crate::json::escribir(&Valor::Mapa(actual.clone()), 1)).map_err(|e| ErrorPy::os(&e, &tmp))?;
    std::fs::rename(&tmp, &ruta).map_err(|e| ErrorPy::os2(&e, &tmp, &ruta))?;
    let _ = Path::new(&ruta);
    Ok(actual)
}

// =========================================================================== actividad

fn estado_desafio(v: &Valor) -> R<&'static str> {
    py::hasheable(v)?;
    Ok(match v {
        Valor::Texto(t) => match t.as_str() {
            "resuelto" => "Resolviste",
            "en_curso" => "Trabajaste en",
            "rendido" => "Viste la solución de",
            "nuevo" => "Empezaste",
            _ => "Trabajaste en",
        },
        _ => "Trabajaste en",
    })
}

/// `_cuando`: los primeros 19 caracteres (fecha y hora, sin fracciones ni zona)
fn cuando(v: &Valor) -> String {
    cortar(&texto_o_vacio(v), 19)
}

fn o(a: Valor, b: impl FnOnce() -> R<Valor>) -> R<Valor> {
    if a.verdad() {
        Ok(a)
    } else {
        b()
    }
}

/// `lista[:n]`
fn primeros(v: &Valor, n: usize) -> R<Vec<Valor>> {
    match v {
        Valor::Lista(l) => Ok(l.iter().take(n).cloned().collect()),
        Valor::Texto(t) => Ok(t.chars().take(n).map(|c| Valor::Texto(c.to_string())).collect()),
        // un dict con una porción por clave
        Valor::Mapa(_) => Err(ErrorPy::Clave(format!("slice(None, {n}, None)"))),
        otro => Err(ErrorPy::Tipo(format!("'{}' object is not subscriptable", py::tipo(otro)))),
    }
}

/// `actividad(...)`: [{tipo, icono, texto, detalle, fecha, abrir}] del más reciente al más antiguo
pub fn actividad(
    historial: &Valor,
    lecturas: &Valor,
    colecciones: &Valor,
    descargas: &Valor,
    ejercicios: &Valor,
    n: usize,
) -> R<Vec<Valor>> {
    let mut eventos: Vec<Mapa> = Vec::new();
    for d in primeros(historial, 30)? {
        let verbo = estado_desafio(&get_py(&d, "estado")?)?;
        let mejor = o(get_py(&d, "mejor")?, || Ok(Valor::Mapa(Mapa::new())))?;
        let mut detalle = Vec::new();
        if get_py(&mejor, "total")?.verdad() {
            let pasados = py::get(&mejor, "pasados", Valor::Entero(0)).map_err(ErrorPy::Atributo)?;
            let total = py::item(&mejor, "total").map_err(ErrorPy::Tipo)?;
            detalle.push(format!("{}/{} pruebas", pasados.texto_py(), total.texto_py()));
        }
        let intentos = get_py(&d, "intentos")?;
        if intentos.verdad() {
            detalle.push(format!("{} intentos", py::item(&d, "intentos").map_err(ErrorPy::Tipo)?.texto_py()));
        }
        if get_py(&d, "conceptos")?.verdad() {
            let c = py::item(&d, "conceptos").map_err(ErrorPy::Tipo)?;
            let tres = Valor::Lista(primeros(&c, 3)?);
            detalle.push(py::unir(", ", &tres).map_err(ErrorPy::Tipo)?);
        }
        let fecha = cuando(&o(get_py(&d, "actualizado")?, || get_py(&d, "creado"))?);
        eventos.push(
            Mapa::new()
                .con("tipo", "desafio")
                .con("icono", "fa-chess-knight")
                .con("texto", format!("{verbo} el desafío «{}»", get_py(&d, "titulo")?.texto_py()))
                .con("detalle", detalle.join(" · "))
                .con("fecha", fecha)
                .con("estado", get_py(&d, "estado")?)
                .con("abrir", Mapa::new().con("desafio", get_py(&d, "id")?)),
        );
    }
    for l in primeros(lecturas, 20)? {
        eventos.push(
            Mapa::new()
                .con("tipo", "kaggle")
                .con("icono", "fa-book-open-reader")
                .con("texto", format!("Leíste «{}» con el profesor", get_py(&l, "titulo")?.texto_py()))
                .con("detalle", format!("{} de {} celdas", get_py(&l, "leidas")?.texto_py(), get_py(&l, "total")?.texto_py()))
                .con("fecha", cuando(&get_py(&l, "ultima")?))
                .con(
                    "abrir",
                    Mapa::new().con(
                        "kaggle",
                        Mapa::new().con("tipo", "notebook").con("ref", get_py(&l, "ref")?).con("celda", get_py(&l, "ultima_celda")?),
                    ),
                ),
        );
    }
    for it in primeros(colecciones, 20)? {
        let tipo = get_py(&it, "tipo")?;
        py::hasheable(&tipo)?;
        let nombre = match &tipo {
            Valor::Texto(t) if t == "notebook" => "el notebook",
            Valor::Texto(t) if t == "dataset" => "el dataset",
            Valor::Texto(t) if t == "competicion" => "la competición",
            _ => "",
        };
        eventos.push(
            Mapa::new()
                .con("tipo", "coleccion")
                .con("icono", "fa-bookmark")
                .con("texto", format!("Guardaste {nombre} «{}»", get_py(&it, "titulo")?.texto_py()))
                .con("detalle", format!("en «{}»", get_py(&it, "coleccion")?.texto_py()))
                .con("fecha", cuando(&get_py(&it, "anadido")?))
                .con("abrir", Mapa::new().con("kaggle", Mapa::new().con("tipo", tipo).con("ref", get_py(&it, "ref")?))),
        );
    }
    for d in primeros(descargas, 20)? {
        if !get_py(&d, "fecha")?.verdad() {
            continue;
        }
        let tipo = get_py(&d, "tipo")?;
        let abrir = if tipo.verdad() {
            Valor::Mapa(Mapa::new().con("kaggle", Mapa::new().con("tipo", tipo).con("ref", get_py(&d, "ref")?)))
        } else {
            Valor::Nulo
        };
        eventos.push(
            Mapa::new()
                .con("tipo", "datos")
                .con("icono", "fa-download")
                .con("texto", format!("Descargaste los datos de «{}»", get_py(&d, "nombre")?.texto_py()))
                .con("detalle", o(get_py(&d, "relativa")?, || Ok(Valor::Texto(String::new())))?)
                .con("fecha", cuando(&get_py(&d, "fecha")?))
                .con("abrir", abrir),
        );
    }
    for e in primeros(ejercicios, 20)? {
        let verbo = if get_py(&e, "resuelto")?.verdad() { "Resolviste" } else { "Practicaste" };
        eventos.push(
            Mapa::new()
                .con("tipo", "ejercicio")
                .con("icono", "fa-dumbbell")
                .con("texto", format!("{verbo} un ejercicio de {}", get_py(&e, "concepto")?.texto_py()))
                .con("detalle", format!("{} envíos", get_py(&e, "envios")?.texto_py()))
                .con("fecha", cuando(&get_py(&e, "fecha")?))
                .con("abrir", Valor::Nulo),
        );
    }
    let mut eventos: Vec<Mapa> = eventos.into_iter().filter(|e| e.valor("fecha").verdad()).collect();
    eventos.sort_by(|a, b| b.texto("fecha").cmp(&a.texto("fecha")));
    Ok(eventos.into_iter().take(n).map(Valor::Mapa).collect())
}

/// `int(v)` con los errores de Python
fn int_py(v: &Valor) -> R<i128> {
    match v {
        Valor::Real(x) if !x.is_finite() => Err(ErrorPy::Valor(if x.is_nan() {
            "cannot convert float NaN to integer".into()
        } else {
            "cannot convert float infinity to integer".into()
        })),
        Valor::Texto(t) => v.entero().ok_or_else(|| {
            ErrorPy::Valor(format!("invalid literal for int() with base 10: {}", Valor::Texto(t.clone()).repr_py()))
        }),
        Valor::Nulo | Valor::Lista(_) | Valor::Mapa(_) => Err(ErrorPy::Tipo(format!(
            "int() argument must be a string, a bytes-like object or a real number, not '{}'",
            py::tipo(v)
        ))),
        otro => Ok(otro.entero().unwrap_or(0)),
    }
}

/// `semana(actividad_por_dia)`: los últimos días con su número de acciones
pub fn semana(por_dia: &Valor, dias: i64) -> R<Vec<Valor>> {
    // SAFETY: time y localtime_r escriben en las estructuras que se les dan
    let (mut y, mut m, mut d) = unsafe {
        let t = libc::time(std::ptr::null_mut());
        let mut tm: libc::tm = std::mem::zeroed();
        libc::localtime_r(&t, &mut tm);
        (tm.tm_year as i64 + 1900, tm.tm_mon as i64 + 1, tm.tm_mday as i64)
    };
    let hoy = dias_desde_epoca(y, m, d);
    let mut salida = Vec::new();
    for i in (0..dias).rev() {
        let n = hoy - i;
        (y, m, d) = fecha_de_dias(n);
        let iso = format!("{y:04}-{m:02}-{d:02}");
        // 1970-01-01 fue jueves (weekday 3)
        let dia_semana = (n + 3).rem_euclid(7) as usize;
        let cuenta = py::get(por_dia, &iso, Valor::Entero(0)).map_err(ErrorPy::Atributo)?;
        let dia = "LMXJVSD".chars().nth(dia_semana).unwrap().to_string();
        salida.push(Valor::Mapa(Mapa::new().con("fecha", iso).con("dia", dia).con("n", int_py(&cuenta)?)));
    }
    Ok(salida)
}

fn dias_desde_epoca(y: i64, m: i64, d: i64) -> i64 {
    let y = if m <= 2 { y - 1 } else { y };
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let mp = (m + 9) % 12;
    let doy = (153 * mp + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146097 + doe - 719468
}

fn fecha_de_dias(z: i64) -> (i64, i64, i64) {
    let z = z + 719468;
    let era = z.div_euclid(146097);
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    (if m <= 2 { y + 1 } else { y }, m, d)
}
