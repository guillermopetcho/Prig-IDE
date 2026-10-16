//! Lo de Python que cambia el resultado si se hace «a la Rust»: `os.path` (rutas sin resolver enlaces), el texto de
//! los errores del sistema (`[Errno 2] No such file or directory: '/x'`), `os.makedirs`, leer un archivo de texto con
//! `errors="replace"` y saltos universales, y las operaciones sobre valores de JSON que lanzan TypeError o
//! AttributeError con sus mensajes.

use crate::valor::{Mapa, Valor};
use std::ffi::CStr;
use std::io;
use std::path::Path;

// =========================================================================== os.path

/// `os.path.isabs`
pub fn isabs(p: &str) -> bool {
    p.starts_with('/')
}

/// `os.path.normpath` (posix): sin `.` ni `..` ni barras de más; conserva exactamente dos barras al principio
pub fn normpath(p: &str) -> String {
    if p.is_empty() {
        return ".".into();
    }
    let iniciales = if p.starts_with("//") && !p.starts_with("///") {
        2
    } else if p.starts_with('/') {
        1
    } else {
        0
    };
    let mut comps: Vec<&str> = Vec::new();
    for c in p.split('/') {
        if c.is_empty() || c == "." {
            continue;
        }
        if c != ".." || (iniciales == 0 && comps.is_empty()) || comps.last() == Some(&"..") {
            comps.push(c);
        } else if !comps.is_empty() {
            comps.pop();
        }
    }
    let s = format!("{}{}", "/".repeat(iniciales), comps.join("/"));
    if s.is_empty() {
        ".".into()
    } else {
        s
    }
}

/// `os.getcwd()`
pub fn getcwd() -> String {
    std::env::current_dir().map(|p| p.to_string_lossy().into_owned()).unwrap_or_else(|_| "/".into())
}

/// `os.path.abspath`
pub fn abspath(p: &str) -> String {
    if isabs(p) {
        normpath(p)
    } else {
        normpath(&join(&getcwd(), p))
    }
}

/// `os.path.join(a, b)`
pub fn join(a: &str, b: &str) -> String {
    if isabs(b) {
        b.to_string()
    } else if a.is_empty() || a.ends_with('/') {
        format!("{a}{b}")
    } else {
        format!("{a}/{b}")
    }
}

/// `os.path.split`
pub fn split(p: &str) -> (String, String) {
    let i = p.rfind('/').map(|i| i + 1).unwrap_or(0);
    let (cabeza, cola) = p.split_at(i);
    let cabeza = if !cabeza.is_empty() && cabeza.chars().any(|c| c != '/') { cabeza.trim_end_matches('/') } else { cabeza };
    (cabeza.to_string(), cola.to_string())
}

/// `os.path.basename`
pub fn basename(p: &str) -> String {
    split(p).1
}

/// `os.path.dirname`
pub fn dirname(p: &str) -> String {
    split(p).0
}

/// `os.path.splitext(p)[1]`: la extensión, sin contar los puntos del principio del nombre
pub fn extension(p: &str) -> String {
    let nombre = basename(p);
    match nombre.rfind('.') {
        Some(i) if nombre[..i].chars().any(|c| c != '.') => nombre[i..].to_string(),
        _ => String::new(),
    }
}

/// `os.path.commonpath([a, b]) == raiz`, con ValueError (rutas absolutas y relativas mezcladas) como `None`
pub fn bajo_raiz(abs_path: &str, raiz: &str) -> Option<bool> {
    if isabs(abs_path) != isabs(raiz) {
        return None;
    }
    let partes = |s: &str| s.split('/').filter(|c| !c.is_empty() && *c != ".").map(String::from).collect::<Vec<_>>();
    let (a, b) = (partes(abs_path), partes(raiz));
    let comunes: Vec<String> = a.iter().zip(b.iter()).take_while(|(x, y)| x == y).map(|(x, _)| x.clone()).collect();
    let prefijo = if isabs(raiz) { "/" } else { "" };
    Some(format!("{prefijo}{}", comunes.join("/")) == raiz)
}

// =========================================================================== errores del sistema

/// `strerror(errno)`, el texto que pone Python
pub fn strerror(errno: i32) -> String {
    // SAFETY: strerror devuelve un puntero a un texto estático de la libc
    unsafe { CStr::from_ptr(libc::strerror(errno)) }.to_string_lossy().into_owned()
}

/// `str(OSError)` con nombre de archivo: `[Errno 2] No such file or directory: '/x'`
pub fn error_os(e: &io::Error, ruta: &str) -> String {
    match e.raw_os_error() {
        Some(n) => format!("[Errno {n}] {}: {}", strerror(n), Valor::Texto(ruta.to_string()).repr_py()),
        None if e.kind() == io::ErrorKind::InvalidInput => "embedded null byte".into(),
        None => e.to_string(),
    }
}

fn existe(p: &str) -> bool {
    Path::new(p).exists()
}

/// `os.makedirs(nombre, exist_ok=True)`, con el error que daría Python (el texto de `str(e)`)
pub fn makedirs(nombre: &str) -> Result<(), String> {
    makedirs_py(nombre).map_err(|e| e.texto())
}

/// `os.makedirs(nombre, exist_ok=True)`, con la excepción que daría Python
pub fn makedirs_py(nombre: &str) -> Result<(), ErrorPy> {
    let (mut cabeza, mut cola) = split(nombre);
    if cola.is_empty() {
        (cabeza, cola) = split(&cabeza);
    }
    if !cabeza.is_empty() && !cola.is_empty() && !existe(&cabeza) {
        match makedirs_py(&cabeza) {
            Ok(()) => {}
            Err(ErrorPy::Os { errno: 17, .. }) => {}
            Err(e) => return Err(e),
        }
        if cola == "." {
            return Ok(());
        }
    }
    if nombre.contains('\0') {
        return Err(ErrorPy::Valor("embedded null byte".into()));
    }
    match std::fs::create_dir(nombre) {
        Ok(()) => Ok(()),
        Err(e) => {
            if Path::new(nombre).is_dir() {
                Ok(())
            } else {
                Err(ErrorPy::os(&e, nombre))
            }
        }
    }
}

/// `open(ruta, "r", encoding="utf-8", errors="replace").read()`: los bytes no válidos como U+FFFD y los saltos
/// `\r\n` y `\r` como `\n`
pub fn leer_texto(ruta: &str) -> Result<String, String> {
    if ruta.contains('\0') {
        return Err("embedded null byte".into());
    }
    let bytes = std::fs::read(ruta).map_err(|e| error_os(&e, ruta))?;
    let crudo = String::from_utf8_lossy(&bytes);
    let mut s = String::with_capacity(crudo.len());
    let mut it = crudo.chars().peekable();
    while let Some(c) = it.next() {
        if c == '\r' {
            if it.peek() == Some(&'\n') {
                it.next();
            }
            s.push('\n');
        } else {
            s.push(c);
        }
    }
    Ok(s)
}

/// `open(ruta, "w", encoding="utf-8").write(texto)`
pub fn escribir_texto(ruta: &str, texto: &str) -> Result<(), String> {
    if ruta.contains('\0') {
        return Err("embedded null byte".into());
    }
    std::fs::write(ruta, texto).map_err(|e| error_os(&e, ruta))
}

// =========================================================================== valores

/// El nombre del tipo de Python (`type(v).__name__`)
pub fn tipo(v: &Valor) -> &'static str {
    match v {
        Valor::Nulo => "NoneType",
        Valor::Bool(_) => "bool",
        Valor::Entero(_) => "int",
        Valor::Real(_) => "float",
        Valor::Texto(_) => "str",
        Valor::Lista(_) => "list",
        Valor::Mapa(_) => "dict",
    }
}

/// `v.get(clave, defecto)`: AttributeError si no es un dict
pub fn get(v: &Valor, clave: &str, defecto: Valor) -> Result<Valor, String> {
    match v {
        Valor::Mapa(m) => Ok(m.get(clave).cloned().unwrap_or(defecto)),
        otro => Err(format!("'{}' object has no attribute 'get'", tipo(otro))),
    }
}

/// `for x in v`: un dict da sus claves y un texto sus caracteres
pub fn iterar(v: &Valor) -> Result<Vec<Valor>, String> {
    match v {
        Valor::Lista(l) => Ok(l.clone()),
        Valor::Mapa(m) => Ok(m.claves().map(|k| Valor::Texto(k.clone())).collect()),
        Valor::Texto(t) => Ok(t.chars().map(|c| Valor::Texto(c.to_string())).collect()),
        otro => Err(format!("'{}' object is not iterable", tipo(otro))),
    }
}

/// `sep.join(v)`
pub fn unir(sep: &str, v: &Valor) -> Result<String, String> {
    let elementos = match v {
        Valor::Lista(_) | Valor::Mapa(_) | Valor::Texto(_) => iterar(v)?,
        _ => return Err("can only join an iterable".into()),
    };
    let mut partes = Vec::with_capacity(elementos.len());
    for (i, e) in elementos.iter().enumerate() {
        match e {
            Valor::Texto(t) => partes.push(t.clone()),
            otro => return Err(format!("sequence item {i}: expected str instance, {} found", tipo(otro))),
        }
    }
    Ok(partes.join(sep))
}

/// `clave in v`
pub fn contiene(v: &Valor, clave: &str) -> Result<bool, String> {
    match v {
        Valor::Mapa(m) => Ok(m.contiene(clave)),
        Valor::Lista(l) => Ok(l.iter().any(|x| matches!(x, Valor::Texto(t) if t == clave))),
        Valor::Texto(t) => Ok(t.contains(clave)),
        otro => Err(format!("argument of type '{}' is not iterable", tipo(otro))),
    }
}

/// `v[clave]` con una clave de texto (después de comprobar `clave in v`)
pub fn item(v: &Valor, clave: &str) -> Result<Valor, String> {
    match v {
        Valor::Mapa(m) => m.get(clave).cloned().ok_or_else(|| Valor::Texto(clave.into()).repr_py()),
        Valor::Lista(_) => Err("list indices must be integers or slices, not str".into()),
        Valor::Texto(_) => Err("string indices must be integers, not 'str'".into()),
        otro => Err(format!("'{}' object is not subscriptable", tipo(otro))),
    }
}

/// `m.items()` de un dict
pub fn items(m: &Mapa) -> Vec<(String, Valor)> {
    m.iter().map(|(k, v)| (k.clone(), v.clone())).collect()
}

/// `os.path.expanduser`: `~` y `~/...` con `$HOME` (o la cuenta), `~usuario` con la base de datos de cuentas
pub fn expanduser(p: &str) -> String {
    if !p.starts_with('~') {
        return p.to_string();
    }
    let fin = p.find('/').unwrap_or(p.len());
    let usuario = &p[1..fin];
    let casa = if usuario.is_empty() {
        match std::env::var("HOME") {
            Ok(h) => Some(h),
            Err(_) => casa_de(None),
        }
    } else {
        casa_de(Some(usuario))
    };
    match casa {
        Some(h) => {
            let h = if h == "/" { String::new() } else { h.trim_end_matches('/').to_string() };
            let resto = &p[fin..];
            let r = format!("{h}{resto}");
            if r.is_empty() {
                "/".into()
            } else {
                r
            }
        }
        None => p.to_string(),
    }
}

fn casa_de(usuario: Option<&str>) -> Option<String> {
    // SAFETY: getpwnam/getpwuid devuelven un puntero a una estructura estática de la libc, que se copia enseguida
    unsafe {
        let pw = match usuario {
            Some(u) => {
                let c = std::ffi::CString::new(u).ok()?;
                libc::getpwnam(c.as_ptr())
            }
            None => libc::getpwuid(libc::getuid()),
        };
        if pw.is_null() || (*pw).pw_dir.is_null() {
            return None;
        }
        Some(CStr::from_ptr((*pw).pw_dir).to_string_lossy().into_owned())
    }
}

// =========================================================================== excepciones

/// Una excepción de Python, para que la fachada la lance igual que lanzaba el código de Python
#[derive(Debug, Clone, PartialEq)]
pub enum ErrorPy {
    /// La excepción propia del módulo (ErrorIDE)
    Propia(String),
    Permiso(String),
    /// OSError(errno, strerror, archivo[, archivo2]): Python elige la subclase (FileNotFoundError, ...)
    Os { errno: i32, ruta: String, ruta2: Option<String> },
    /// Un OSError sin errno (p. ej. «Cannot call rmtree on a symbolic link»)
    OsTexto(String),
    /// NotADirectoryError con un texto propio
    NoEsCarpeta(String),
    /// KeyError (el texto es el `str()` de la excepción)
    Clave(String),
    /// OverflowError
    Desborde(String),
    /// `shutil.Error`: los errores de una copia de carpeta, en una lista plana (origen, destino, texto)
    Shutil(Vec<(String, String, String)>),
    Atributo(String),
    Tipo(String),
    Valor(String),
}

impl ErrorPy {
    pub fn os(e: &io::Error, ruta: &str) -> ErrorPy {
        match e.raw_os_error() {
            Some(n) => ErrorPy::Os { errno: n, ruta: ruta.to_string(), ruta2: None },
            None if e.kind() == io::ErrorKind::InvalidInput => ErrorPy::Valor("embedded null byte".into()),
            None => ErrorPy::OsTexto(e.to_string()),
        }
    }

    pub fn os2(e: &io::Error, a: &str, b: &str) -> ErrorPy {
        match e.raw_os_error() {
            Some(n) => ErrorPy::Os { errno: n, ruta: a.to_string(), ruta2: Some(b.to_string()) },
            None => ErrorPy::os(e, a),
        }
    }

    /// `str(e)`
    pub fn texto(&self) -> String {
        match self {
            ErrorPy::Os { errno, ruta, ruta2: None } => {
                format!("[Errno {errno}] {}: {}", strerror(*errno), Valor::Texto(ruta.clone()).repr_py())
            }
            ErrorPy::Os { errno, ruta, ruta2: Some(b) } => format!(
                "[Errno {errno}] {}: {} -> {}",
                strerror(*errno),
                Valor::Texto(ruta.clone()).repr_py(),
                Valor::Texto(b.clone()).repr_py()
            ),
            ErrorPy::Shutil(lista) => {
                let r = |t: &String| Valor::Texto(t.clone()).repr_py();
                let partes: Vec<String> = lista.iter().map(|(a, b, c)| format!("({}, {}, {})", r(a), r(b), r(c))).collect();
                format!("[{}]", partes.join(", "))
            }
            ErrorPy::Propia(t)
            | ErrorPy::Permiso(t)
            | ErrorPy::OsTexto(t)
            | ErrorPy::NoEsCarpeta(t)
            | ErrorPy::Clave(t)
            | ErrorPy::Desborde(t)
            | ErrorPy::Atributo(t)
            | ErrorPy::Tipo(t)
            | ErrorPy::Valor(t) => t.clone(),
        }
    }
}

/// `os.fspath(v)` para las funciones de `os.path`: TypeError si no es un texto
pub fn ruta_de(v: &Valor) -> Result<&str, ErrorPy> {
    match v {
        Valor::Texto(t) => Ok(t),
        otro => Err(ErrorPy::Tipo(format!("expected str, bytes or os.PathLike object, not {}", tipo(otro)))),
    }
}

/// `os.path.isdir(v)` con lo que acepta Python: un texto, o un entero (un descriptor abierto)
pub fn isdir_valor(v: &Valor) -> Result<bool, ErrorPy> {
    match v {
        Valor::Texto(t) => Ok(!t.contains('\0') && Path::new(t).is_dir()),
        Valor::Entero(_) | Valor::Bool(_) => {
            let fd = v.entero().unwrap_or(-1);
            if fd < i32::MIN as i128 || fd > i32::MAX as i128 {
                return Err(ErrorPy::Tipo("fd is greater than maximum".into()));
            }
            // SAFETY: fstat solo escribe en la estructura que se le da
            let mut st: libc::stat = unsafe { std::mem::zeroed() };
            let r = unsafe { libc::fstat(fd as i32, &mut st) };
            Ok(r == 0 && (st.st_mode & libc::S_IFMT) == libc::S_IFDIR)
        }
        otro => Err(ErrorPy::Tipo(format!("stat: path should be string, bytes, os.PathLike or integer, not {}", tipo(otro)))),
    }
}

/// `for x in v` con el TypeError de Python
pub fn iterar_py(v: &Valor) -> Result<Vec<Valor>, ErrorPy> {
    iterar(v).map_err(ErrorPy::Tipo)
}

/// `v.get(clave)` con el AttributeError de Python
pub fn get_py(v: &Valor, clave: &str) -> Result<Valor, ErrorPy> {
    get(v, clave, Valor::Nulo).map_err(ErrorPy::Atributo)
}

/// `v[clave] = x` con el TypeError de Python
pub fn poner_py(v: &mut Valor, clave: &str, x: Valor) -> Result<(), ErrorPy> {
    match v {
        Valor::Mapa(m) => {
            m.poner(clave, x);
            Ok(())
        }
        Valor::Lista(_) => Err(ErrorPy::Tipo("list indices must be integers or slices, not str".into())),
        otro => Err(ErrorPy::Tipo(format!("'{}' object does not support item assignment", tipo(otro)))),
    }
}

/// Que un valor pueda ir en un `set` (TypeError si es una lista o un dict)
pub fn hasheable(v: &Valor) -> Result<(), ErrorPy> {
    match v {
        Valor::Lista(_) | Valor::Mapa(_) => Err(ErrorPy::Tipo(format!("unhashable type: '{}'", tipo(v)))),
        _ => Ok(()),
    }
}

/// `os.path.relpath(ruta, inicio)`
pub fn relpath(ruta: &str, inicio: &str) -> String {
    let a = abspath(ruta);
    let b = abspath(inicio);
    let pa: Vec<&str> = a.split('/').filter(|x| !x.is_empty()).collect();
    let pb: Vec<&str> = b.split('/').filter(|x| !x.is_empty()).collect();
    let comunes = pa.iter().zip(pb.iter()).take_while(|(x, y)| x == y).count();
    let mut partes: Vec<&str> = vec![".."; pb.len() - comunes];
    partes.extend_from_slice(&pa[comunes..]);
    if partes.is_empty() {
        ".".into()
    } else {
        partes.join("/")
    }
}

/// `os.path.splitext(p)`: (raíz, extensión)
pub fn splitext(p: &str) -> (String, String) {
    let ext = extension(p);
    (p[..p.len() - ext.len()].to_string(), ext)
}

/// `str.strip()`
pub fn strip(t: &str) -> &str {
    t.trim_matches(|c: char| c.is_whitespace() || ('\x1c'..='\x1f').contains(&c))
}

/// `datetime.datetime.now().isoformat()`: hora local con microsegundos (sin ellos si son 0)
pub fn ahora_iso() -> String {
    // SAFETY: clock_gettime y localtime_r escriben en las estructuras que se les dan
    unsafe {
        let mut ts: libc::timespec = std::mem::zeroed();
        libc::clock_gettime(libc::CLOCK_REALTIME, &mut ts);
        let mut tm: libc::tm = std::mem::zeroed();
        libc::localtime_r(&ts.tv_sec, &mut tm);
        let micro = ts.tv_nsec / 1000;
        let base = format!(
            "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}",
            tm.tm_year + 1900,
            tm.tm_mon + 1,
            tm.tm_mday,
            tm.tm_hour,
            tm.tm_min,
            tm.tm_sec
        );
        if micro == 0 {
            base
        } else {
            format!("{base}.{micro:06}")
        }
    }
}

/// `os.path.realpath(p)` (strict=False): resuelve los enlaces hasta donde se pueda, con la misma vuelta que Python
/// en los bucles de enlaces
pub fn realpath(p: &str) -> String {
    let mut vistos: std::collections::HashMap<String, Option<String>> = std::collections::HashMap::new();
    let (ruta, _) = unir_real(String::new(), p, &mut vistos);
    abspath(&ruta)
}

fn unir_real(mut ruta: String, resto: &str, vistos: &mut std::collections::HashMap<String, Option<String>>) -> (String, bool) {
    let mut resto = resto.to_string();
    if isabs(&resto) {
        resto = resto[1..].to_string();
        ruta = "/".into();
    }
    while !resto.is_empty() {
        let (nombre, r) = match resto.find('/') {
            Some(i) => (resto[..i].to_string(), resto[i + 1..].to_string()),
            None => (resto.clone(), String::new()),
        };
        resto = r;
        if nombre.is_empty() || nombre == "." {
            continue;
        }
        if nombre == ".." {
            if !ruta.is_empty() {
                let (cabeza, cola) = split(&ruta);
                ruta = cabeza;
                if cola == ".." {
                    ruta = join(&join(&ruta, ".."), "..");
                }
            } else {
                ruta = "..".into();
            }
            continue;
        }
        let nueva = join(&ruta, &nombre);
        let enlace = !nueva.contains('\0')
            && std::fs::symlink_metadata(&nueva).map(|m| m.file_type().is_symlink()).unwrap_or(false);
        if !enlace {
            ruta = nueva;
            continue;
        }
        if let Some(visto) = vistos.get(&nueva) {
            match visto {
                Some(p) => {
                    ruta = p.clone();
                    continue;
                }
                None => return (join(&nueva, &resto), false),
            }
        }
        vistos.insert(nueva.clone(), None);
        let destino = std::fs::read_link(&nueva).map(|l| l.to_string_lossy().into_owned()).unwrap_or_default();
        let (p, ok) = unir_real(ruta, &destino, vistos);
        if !ok {
            return (join(&p, &resto), false);
        }
        ruta = p.clone();
        vistos.insert(nueva, Some(p));
    }
    (ruta, true)
}

/// `time.strftime("%Y-%m-%d", time.localtime(t))`
pub fn fecha_local(t: f64) -> String {
    let s = t.floor() as libc::time_t;
    // SAFETY: localtime_r escribe en la estructura que se le da
    unsafe {
        let mut tm: libc::tm = std::mem::zeroed();
        libc::localtime_r(&s, &mut tm);
        format!("{:04}-{:02}-{:02}", tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday)
    }
}

/// `open(ruta, encoding="utf-8").read()` (sin `errors`): UTF-8 estricto, con saltos universales
pub fn leer_texto_estricto(ruta: &str) -> Result<String, String> {
    let bytes = std::fs::read(ruta).map_err(|e| error_os(&e, ruta))?;
    let t = String::from_utf8(bytes).map_err(|e| crate::ejecucion::decodificar(e.as_bytes()).err().unwrap_or_default())?;
    Ok(t.replace("\r\n", "\n").replace('\r', "\n"))
}
