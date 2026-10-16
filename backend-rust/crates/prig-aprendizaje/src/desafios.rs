//! El almacén de desafíos (`backend/desafios/almacen.py`): un JSON por desafío. `lista` lee todos los archivos en
//! cada llamada (el perfil, el hub y el progreso la piden); aquí se leen y se analizan en paralelo, con el JSON de
//! `json.load` (prig_recursos::json) y el mismo resumen, clave por clave y en el mismo orden.
//!
//! Desvíos escritos: un archivo cuyo JSON no es un objeto, o cuyo `progreso` no es un objeto, se salta (en Python
//! hacía fallar la lista entera con AttributeError); un `actualizado` que no es texto ordena como "" (en Python,
//! TypeError al comparar).

use prig_recursos::json;
use prig_recursos::valor::{Mapa, Valor};
use std::path::Path;

/// `d.get(clave) or defecto` de Python
fn o<'a>(m: &'a Mapa, clave: &str, defecto: &'a Valor) -> &'a Valor {
    match m.get(clave) {
        Some(v) if v.verdad() => v,
        _ => defecto,
    }
}

fn get(m: &Mapa, clave: &str) -> Valor {
    m.get(clave).cloned().unwrap_or(Valor::Nulo)
}

/// El resumen de un desafío (`Almacen.lista`), o None si el archivo no vale
fn resumen(texto: &str) -> Option<Mapa> {
    let Valor::Mapa(d) = json::leer(texto).ok()? else { return None };
    let vacio = Valor::Mapa(Mapa::new());
    let p = match o(&d, "progreso", &vacio) {
        Valor::Mapa(p) => p.clone(),
        _ => return None,
    };
    let sin = |m: &Mapa, quitar: &str| {
        let mut r = Mapa::new();
        for (k, v) in m.iter() {
            if k != quitar {
                r.poner(k.clone(), v.clone());
            }
        }
        r
    };
    let origen = match o(&d, "origen", &vacio) {
        Valor::Mapa(m) => sin(m, "tema"),
        _ => return None,
    };
    let verificable = match o(&d, "comprobacion", &vacio) {
        Valor::Mapa(m) => !matches!(m.get("tipo"), Some(Valor::Texto(t)) if t == "ninguna"),
        _ => return None,
    };
    let lista_vacia = Valor::Lista(Vec::new());
    let mut r = Mapa::new();
    r.poner("id", get(&d, "id"));
    r.poner("titulo", get(&d, "titulo"));
    r.poner("nivel", get(&d, "nivel"));
    r.poner("conceptos", o(&d, "conceptos", &lista_vacia).clone());
    r.poner("origen", Valor::Mapa(origen));
    r.poner("verificable", Valor::Bool(verificable));
    r.poner("estado", p.get("estado").cloned().unwrap_or(Valor::Texto("nuevo".into())));
    r.poner("intentos", p.get("intentos").cloned().unwrap_or(Valor::Entero(0)));
    r.poner("pistas", p.get("pistas").cloned().unwrap_or(Valor::Entero(0)));
    r.poner("mejor", get(&p, "mejor"));
    r.poner("creado", get(&d, "creado"));
    r.poner("actualizado", get(&d, "actualizado"));
    r.poner("progreso", Valor::Mapa(sin(&p, "historial")));
    Some(r)
}

/// `Almacen.lista()` sobre la carpeta `desafios`: de más a menos reciente (`actualizado`)
pub fn lista(dir: &Path) -> std::io::Result<Vec<Mapa>> {
    if !dir.is_dir() {
        return Ok(Vec::new());
    }
    // el orden de os.listdir (el del sistema de archivos): a igual fecha, el sort de Python lo conserva
    let rutas: Vec<_> = std::fs::read_dir(dir)?
        .filter_map(|e| e.ok())
        .filter(|e| e.file_name().to_str().is_some_and(|n| n.ends_with(".json")))
        .map(|e| e.path())
        .collect();
    let leer = |r: &std::path::PathBuf| std::fs::read(r).ok().and_then(|b| String::from_utf8(b).ok()).and_then(|t| resumen(&t));
    let hilos = std::thread::available_parallelism().map_or(1, |n| n.get()).min(8);
    let mut salida: Vec<Mapa> = if rutas.len() < 32 || hilos == 1 {
        rutas.iter().filter_map(leer).collect()
    } else {
        let trozo = rutas.len().div_ceil(hilos);
        std::thread::scope(|s| {
            let tareas: Vec<_> = rutas.chunks(trozo).map(|c| s.spawn(move || c.iter().filter_map(leer).collect::<Vec<_>>())).collect();
            tareas.into_iter().flat_map(|t| t.join().unwrap()).collect()
        })
    };
    let clave = |m: &Mapa| match m.get("actualizado") {
        Some(Valor::Texto(t)) => t.clone(),
        _ => String::new(),
    };
    // sorted(..., reverse=True) es estable: los iguales quedan en su orden
    salida.sort_by_key(|m| std::cmp::Reverse(clave(m)));
    Ok(salida)
}

/// Error de `Almacen.obtener` (ErrorDesafio: la ruta responde 400) o de otro tipo (500)
pub enum ErrorObtener {
    Desafio(String),
    Otro(String),
}

/// `ID_VALIDO`: `des_` y diez cifras hexadecimales en minúscula
pub fn id_valido(id: &str) -> bool {
    id.len() == 14 && id.starts_with("des_") && id[4..].chars().all(|c| c.is_ascii_digit() || ('a'..='f').contains(&c))
}

/// `Almacen.obtener(id)`: el desafío entero
pub fn obtener(dir: &Path, id: &str) -> Result<Valor, ErrorObtener> {
    if !id_valido(id) {
        return Err(ErrorObtener::Desafio("Desafío desconocido".into()));
    }
    let bytes = match std::fs::read(dir.join(format!("{id}.json"))) {
        Ok(b) => b,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Err(ErrorObtener::Desafio("Ese desafío ya no existe.".into())),
        Err(e) => return Err(ErrorObtener::Otro(e.to_string())),
    };
    // un archivo que no es UTF-8 o no es JSON: ValueError en Python
    let texto = String::from_utf8(bytes).map_err(|_| ErrorObtener::Desafio("El archivo del desafío está dañado.".into()))?;
    json::leer(&texto).map_err(|_| ErrorObtener::Desafio("El archivo del desafío está dañado.".into()))
}

/// `Almacen.publico(d)`: todo menos `privado`, con `solucion_disponible` y `pistas_fuente`
pub fn publico(d: &Mapa) -> Mapa {
    let mut vista = Mapa::new();
    for (k, v) in d.iter() {
        if k != "privado" {
            vista.poner(k.clone(), v.clone());
        }
    }
    let vacio = Valor::Mapa(Mapa::new());
    let estado = match o(d, "progreso", &vacio) {
        Valor::Mapa(p) => p.get("estado").cloned(),
        _ => None,
    };
    let resuelto = matches!(estado, Some(Valor::Texto(ref t)) if t == "resuelto" || t == "rendido");
    let pistas = match o(d, "privado", &vacio) {
        Valor::Mapa(p) => p.get("pistas_fuente").is_some_and(Valor::verdad),
        _ => false,
    };
    vista.poner("solucion_disponible", Valor::Bool(resuelto));
    vista.poner("pistas_fuente", Valor::Bool(pistas));
    vista
}

/// Un JSON leído como `json.load` dentro de `try/except (FileNotFoundError, ValueError[, OSError])`: None si falta,
/// está roto o no se puede leer
pub fn leer_json(ruta: &Path) -> Option<Valor> {
    let texto = String::from_utf8(std::fs::read(ruta).ok()?).ok()?;
    json::leer(&texto).ok()
}

// ---------------------------------------------------------------------------------------------- escribir

/// `datetime.now().isoformat(timespec="seconds")`: hora local, sin fracción
pub fn ahora() -> String {
    // SAFETY: time y localtime_r escriben en las estructuras que se les dan
    unsafe {
        let t = libc::time(std::ptr::null_mut());
        let mut tm: libc::tm = std::mem::zeroed();
        libc::localtime_r(&t, &mut tm);
        format!("{:04}-{:02}-{:02}T{:02}:{:02}:{:02}", tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday, tm.tm_hour, tm.tm_min, tm.tm_sec)
    }
}

/// `progreso_inicial()`
pub fn progreso_inicial() -> Mapa {
    Mapa::new()
        .con("estado", "nuevo")
        .con("intentos", Valor::Entero(0))
        .con("pistas", Valor::Entero(0))
        .con("pasos_vistos", Valor::Entero(0))
        .con("plan", "")
        .con("mejor", Mapa::new().con("pasados", Valor::Entero(0)).con("total", Valor::Entero(0)))
        .con("historial", Valor::Lista(Vec::new()))
        .con("empezado", Valor::Nulo)
        .con("resuelto", Valor::Nulo)
        .con("rendido", Valor::Nulo)
        .con("segundos_hasta_resolver", Valor::Nulo)
}

/// `d.setdefault("progreso", progreso_inicial())`
fn progreso(d: &mut Mapa) -> &mut Mapa {
    if !d.contiene("progreso") {
        d.poner("progreso", progreso_inicial());
    }
    match d.get_mut("progreso") {
        Some(Valor::Mapa(m)) => m,
        _ => unreachable!("progreso no es un objeto: se comprueba antes"),
    }
}

/// `Almacen.empezar(d)`
pub fn empezar(d: &mut Mapa) {
    let p = progreso(d);
    if !p.verdad("empezado") {
        p.poner("empezado", ahora());
    }
    if matches!(p.get("estado"), Some(Valor::Texto(t)) if t == "nuevo") {
        p.poner("estado", "en_curso");
    }
}

/// El cerrojo entre procesos que comparte con Python (`Almacen._bloqueo`): flock sobre `<base>/.cerrojo_desafios`
struct Cerrojo(i32);

impl Cerrojo {
    fn tomar(base: &Path) -> std::io::Result<Cerrojo> {
        std::fs::create_dir_all(base)?;
        let ruta = std::ffi::CString::new(base.join(".cerrojo_desafios").to_string_lossy().as_bytes()).map_err(std::io::Error::other)?;
        // SAFETY: open y flock sobre un descriptor propio, que se cierra en Drop
        unsafe {
            let fd = libc::open(ruta.as_ptr(), libc::O_RDWR | libc::O_CREAT | libc::O_CLOEXEC, 0o600);
            if fd < 0 {
                return Err(std::io::Error::last_os_error());
            }
            if libc::flock(fd, libc::LOCK_EX) != 0 {
                let e = std::io::Error::last_os_error();
                libc::close(fd);
                return Err(e);
            }
            Ok(Cerrojo(fd))
        }
    }
}

impl Drop for Cerrojo {
    fn drop(&mut self) {
        // SAFETY: el descriptor es nuestro
        unsafe {
            libc::flock(self.0, libc::LOCK_UN);
            libc::close(self.0);
        }
    }
}

pub const MAX_DESAFIOS: usize = 1000;

/// `Almacen.guardar(d)` (con el cerrojo ya tomado): id, creado, progreso por defecto, `actualizado`, escritura atómica
/// con el formato de `json.dump(..., ensure_ascii=False, indent=1)` y la poda a los 1000 más recientes
fn guardar_sin_cerrojo(dir: &Path, d: &mut Mapa) -> Result<(), ErrorObtener> {
    if !d.contiene("id") {
        d.poner("id", format!("des_{}", &uuid::Uuid::new_v4().simple().to_string()[..10]));
    }
    if !d.contiene("creado") {
        d.poner("creado", ahora());
    }
    let _ = progreso(d);
    d.poner("actualizado", ahora());
    std::fs::create_dir_all(dir).map_err(|e| ErrorObtener::Otro(e.to_string()))?;
    let Some(Valor::Texto(id)) = d.get("id").cloned() else { return Err(ErrorObtener::Desafio("Desafío desconocido".into())) };
    if !id_valido(&id) {
        return Err(ErrorObtener::Desafio("Desafío desconocido".into()));
    }
    let ruta = dir.join(format!("{id}.json"));
    let tmp = dir.join(format!("{id}.json.tmp"));
    std::fs::write(&tmp, json::escribir(&Valor::Mapa(d.clone()), 1)).map_err(|e| ErrorObtener::Otro(e.to_string()))?;
    std::fs::rename(&tmp, &ruta).map_err(|e| ErrorObtener::Otro(e.to_string()))?;
    podar(dir);
    Ok(())
}

/// `_podar`: si hay más de MAX_DESAFIOS, fuera los más viejos (por fecha de modificación)
fn podar(dir: &Path) {
    let Ok(lectura) = std::fs::read_dir(dir) else { return };
    let mut archivos: Vec<(std::time::SystemTime, std::path::PathBuf)> = lectura
        .flatten()
        .filter(|e| e.file_name().to_str().is_some_and(|n| n.ends_with(".json")))
        .filter_map(|e| Some((e.metadata().ok()?.modified().ok()?, e.path())))
        .collect();
    if archivos.len() <= MAX_DESAFIOS {
        return;
    }
    archivos.sort_by_key(|a| a.0);
    let sobran = archivos.len() - MAX_DESAFIOS;
    for (_, r) in archivos.into_iter().take(sobran) {
        let _ = std::fs::remove_file(r);
    }
}

/// `Almacen.modificar(id, cambio)`: leer, cambiar y guardar sin que otro hilo ni otro proceso se cuele en medio
pub fn modificar(base: &Path, id: &str, cambio: impl FnOnce(&mut Mapa) -> Result<(), ErrorObtener>) -> Result<Mapa, ErrorObtener> {
    let _c = Cerrojo::tomar(base).map_err(|e| ErrorObtener::Otro(e.to_string()))?;
    let dir = base.join("desafios");
    let Valor::Mapa(mut d) = obtener(&dir, id)? else { return Err(ErrorObtener::Otro("no es un objeto".into())) };
    if !matches!(d.get("progreso"), None | Some(Valor::Mapa(_))) {
        return Err(ErrorObtener::Otro("progreso no es un objeto".into()));
    }
    cambio(&mut d)?;
    guardar_sin_cerrojo(&dir, &mut d)?;
    Ok(d)
}

/// `Almacen.borrar(id)` (después de comprobar que existe con `obtener`, como la ruta)
pub fn borrar(base: &Path, id: &str) -> Result<bool, ErrorObtener> {
    let _c = Cerrojo::tomar(base).map_err(|e| ErrorObtener::Otro(e.to_string()))?;
    match std::fs::remove_file(base.join("desafios").join(format!("{id}.json"))) {
        Ok(()) => Ok(true),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(e) => Err(ErrorObtener::Otro(e.to_string())),
    }
}

// ---------------------------------------------------------------------------------------------- páginas

pub const MAX_PAGINAS: usize = 8;
pub const MAX_BYTES_PAGINA: usize = 200_000;
const RESERVADOS: [&str; 12] = [
    "pytest.py", "unittest.py", "doctest.py", "json.py", "sys.py", "os.py", "io.py", "traceback.py", "importlib.py",
    "contextlib.py", "catch.hpp", "catch2.hpp",
];

/// `NOMBRE_PAGINA`: `^[A-Za-z_][A-Za-z0-9_]{0,40}\.(py|cpp|hpp|h|cc|cxx|c)$` (`$` admite un salto final, como en
/// Python, pero aquí el nombre ya viene sin blancos alrededor)
fn nombre_valido(n: &str) -> bool {
    let Some((base, ext)) = n.rsplit_once('.') else { return false };
    let mut cs = base.chars();
    let Some(primera) = cs.next() else { return false };
    (primera.is_ascii_alphabetic() || primera == '_')
        && base.chars().count() <= 41
        && cs.all(|c| c.is_ascii_alphanumeric() || c == '_')
        && ["py", "cpp", "hpp", "h", "cc", "cxx", "c"].contains(&ext)
}

/// `str(x)` de Python para un valor JSON (lo que se usa con `str(p.get("nombre", ""))`)
fn a_texto(v: &Valor) -> String {
    match v {
        Valor::Texto(t) => t.clone(),
        otro => otro.repr_py(),
    }
}

/// `validar_paginas(paginas)`: nombres válidos, sin repetir, sin pisar módulos del arnés, tamaño acotado
pub fn validar_paginas(paginas: &[Valor], permitir_vacio: bool) -> Result<Vec<Mapa>, String> {
    if paginas.is_empty() && !permitir_vacio {
        return Err("El desafío necesita al menos una página de código.".into());
    }
    if paginas.len() > MAX_PAGINAS {
        return Err(format!("Como mucho {MAX_PAGINAS} páginas."));
    }
    let mut vistas: Vec<String> = Vec::new();
    let mut salida = Vec::new();
    for p in paginas {
        let m = match p {
            Valor::Mapa(m) => m.clone(),
            _ => Mapa::new(), // `(p or {})`: en una lista de dicts ya validada por pydantic no pasa
        };
        let nombre = prig_recursos_strip(&m.get("nombre").map(a_texto).unwrap_or_default());
        if !nombre_valido(&nombre) {
            return Err(format!(
                "«{nombre}» no es un nombre de página válido: usa letras, números y _, sin espacios ni guiones, terminado en .py, .cpp o .h (por ejemplo pila.py o pila.cpp)."
            ));
        }
        if nombre.starts_with("_prig") || RESERVADOS.contains(&nombre.as_str()) {
            return Err(format!("«{nombre}» está reservado; elige otro nombre."));
        }
        if vistas.contains(&nombre.to_lowercase()) {
            return Err(format!("Hay dos páginas llamadas «{nombre}»."));
        }
        vistas.push(nombre.to_lowercase());
        // `str(p.get("contenido") or "")`
        let contenido = match m.get("contenido") {
            Some(v) if v.verdad() => a_texto(v),
            _ => String::new(),
        };
        if contenido.len() > MAX_BYTES_PAGINA {
            return Err(format!("La página «{nombre}» es demasiado grande."));
        }
        salida.push(m.con("nombre", nombre).con("contenido", contenido));
    }
    Ok(salida)
}

/// `str.strip()` de Python
fn prig_recursos_strip(t: &str) -> String {
    t.trim_matches(|c: char| c.is_whitespace() || ('\x1c'..='\x1f').contains(&c)).to_string()
}

/// `Almacen.registrar_comprobacion(d, resultado)`: intentos, historial (últimos 50), mejor marca y estado
pub fn registrar_comprobacion(d: &mut Mapa, aprobado: bool, pasados: i128, total: i128) {
    let p = progreso(d);
    let intentos = p.get("intentos").and_then(Valor::entero).unwrap_or(0);
    p.poner("intentos", Valor::Entero(intentos + 1));
    if !p.verdad("empezado") {
        p.poner("empezado", ahora());
    }
    let mut historial = match p.get("historial") {
        Some(Valor::Lista(l)) => l.clone(),
        _ => Vec::new(),
    };
    historial.push(Valor::Mapa(
        Mapa::new().con("cuando", ahora()).con("aprobado", aprobado).con("pasados", Valor::Entero(pasados)).con("total", Valor::Entero(total)),
    ));
    let desde = historial.len().saturating_sub(50);
    p.poner("historial", Valor::Lista(historial.split_off(desde)));
    let mejor = match p.get("mejor") {
        Some(Valor::Mapa(m)) => m.get("pasados").and_then(Valor::entero).unwrap_or(0),
        _ => 0,
    };
    if total != 0 && pasados >= mejor {
        p.poner("mejor", Mapa::new().con("pasados", Valor::Entero(pasados)).con("total", Valor::Entero(total)));
    }
    let estado = p.texto("estado").map(String::from);
    if aprobado && estado.as_deref() != Some("resuelto") {
        let resuelto = ahora();
        p.poner("resuelto", resuelto.clone());
        if let (Some(Valor::Texto(e)), Some(r)) = (p.get("empezado").cloned(), crate::telemetria::segundos_iso(&resuelto)) {
            if let Some(i) = crate::telemetria::segundos_iso(&e) {
                p.poner("segundos_hasta_resolver", Valor::Entero((r - i).trunc() as i128));
            }
        }
        // rendirse y luego aprobar copiando la solución no cuenta como resuelto
        if estado.as_deref() != Some("rendido") {
            p.poner("estado", "resuelto");
        }
    } else if estado.as_deref() == Some("nuevo") {
        p.poner("estado", "en_curso");
    }
}

// ---------------------------------------------------------------------------------------------- historial (progreso.py)

/// `progreso._clave(texto)`: minúsculas, NFKD sin marcas, solo `[a-z0-9 ]` y un espacio entre palabras
pub fn clave(texto: &str) -> String {
    use unicode_normalization::char::canonical_combining_class;
    use unicode_normalization::UnicodeNormalization;
    let t: String = texto.to_lowercase().nfkd().filter(|&c| canonical_combining_class(c) == 0).collect();
    let limpio: String = t.chars().map(|c| if c.is_ascii_lowercase() || c.is_ascii_digit() || c == ' ' { c } else { ' ' }).collect();
    limpio.split(' ').filter(|p| !p.is_empty()).collect::<Vec<_>>().join(" ")
}

pub const MAX_HISTORIAL: usize = 500;

/// `progreso.historial(almacen, estado, concepto, fuente, limite)`: cada desafío con lo que hizo el alumno, del más
/// reciente al más antiguo. Err si un dato no tiene la forma que Python espera (allí era una excepción: 500)
pub fn historial(dir: &Path, estado: Option<&str>, concepto: Option<&str>, fuente: Option<&str>, limite: i64) -> Result<Vec<Mapa>, ()> {
    let filas_lista = lista(dir).map_err(|_| ())?;
    let vacio = Valor::Mapa(Mapa::new());
    let mut filas = Vec::new();
    for d in filas_lista {
        let p = match o(&d, "progreso", &vacio) {
            Valor::Mapa(m) => m.clone(),
            _ => return Err(()),
        };
        let origen = match o(&d, "origen", &vacio) {
            Valor::Mapa(m) => m.clone(),
            _ => return Err(()),
        };
        let plan_escrito = match p.get("plan") {
            None | Some(Valor::Nulo) => false,
            Some(Valor::Texto(t)) => !t.trim_matches(|c: char| c.is_whitespace() || ('\x1c'..='\x1f').contains(&c)).is_empty(),
            Some(v) if !v.verdad() => false,
            Some(_) => return Err(()),
        };
        let g = |m: &Mapa, k: &str| m.get(k).cloned().unwrap_or(Valor::Nulo);
        let mejor = match p.get("mejor") {
            Some(v) if v.verdad() => v.clone(),
            _ => Valor::Mapa(Mapa::new().con("pasados", Valor::Entero(0)).con("total", Valor::Entero(0))),
        };
        let fila = Mapa::new()
            .con("id", d.get("id").cloned().ok_or(())?)
            .con("titulo", g(&d, "titulo"))
            .con("nivel", g(&d, "nivel"))
            .con("conceptos", o(&d, "conceptos", &Valor::Lista(Vec::new())).clone())
            .con("estado", p.get("estado").cloned().unwrap_or(Valor::Texto("nuevo".into())))
            .con("verificable", d.get("verificable").cloned().unwrap_or(Valor::Bool(true)))
            .con("fuente", g(&origen, "tipo"))
            .con("fuente_nombre", g(&origen, "nombre"))
            .con("url", g(&origen, "url"))
            .con("ruta_id", g(&origen, "ruta_id"))
            .con("bloque_id", g(&origen, "bloque_id"))
            .con("bloque", g(&origen, "bloque"))
            .con("modelo", g(&origen, "modelo"))
            .con("motor", g(&origen, "motor"))
            .con("intentos", p.get("intentos").cloned().unwrap_or(Valor::Entero(0)))
            .con("pistas", p.get("pistas").cloned().unwrap_or(Valor::Entero(0)))
            .con("pasos_razonamiento", p.get("pasos_vistos").cloned().unwrap_or(Valor::Entero(0)))
            .con("plan_escrito", plan_escrito)
            .con("mejor", mejor)
            .con("segundos", g(&p, "segundos_hasta_resolver"))
            .con("creado", g(&d, "creado"))
            .con("actualizado", g(&d, "actualizado"))
            .con("resuelto", g(&p, "resuelto"))
            .con("rendido", g(&p, "rendido"));
        if let Some(e) = estado.filter(|e| !e.is_empty()) {
            if fila.get("estado") != Some(&Valor::Texto(e.into())) {
                continue;
            }
        }
        if let Some(f) = fuente.filter(|f| !f.is_empty()) {
            if fila.get("fuente") != Some(&Valor::Texto(f.into())) {
                continue;
            }
        }
        if let Some(c) = concepto.filter(|c| !c.is_empty()) {
            let buscada = clave(c);
            let mut claves: Vec<String> = Vec::new();
            if let Some(Valor::Lista(l)) = fila.get("conceptos") {
                for x in l {
                    let Valor::Texto(t) = x else { return Err(()) };
                    claves.push(clave(t));
                }
            }
            claves.push(match fila.get("titulo") {
                Some(Valor::Texto(t)) => clave(t),
                Some(Valor::Nulo) | None => String::new(),
                Some(_) => return Err(()),
            });
            if !claves.contains(&buscada) {
                continue;
            }
        }
        filas.push(fila);
    }
    let n = limite.clamp(1, MAX_HISTORIAL as i64) as usize;
    filas.truncate(n);
    Ok(filas)
}
