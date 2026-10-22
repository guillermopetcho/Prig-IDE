//! Servicios de IDE sobre la carpeta de trabajo (`ide_servicios.py`): listar archivos (Ctrl+P), buscar y reemplazar
//! en todos (Ctrl+Shift+F / H), renombrar, duplicar y mover, carpetas recientes y proyectos guardados, explorar
//! carpetas y mostrar en el explorador del sistema. Todo pasa por `archivos::resolver`: nada sale de la carpeta de
//! trabajo ni de las raíces permitidas. Los problemas de sintaxis de Python los sigue viendo el compilador de Python
//! (Python como herramienta, en la fachada).

use crate::archivos::resolver;
use crate::py::{self, abspath, ErrorPy};
use crate::regex_py::{self, ExpresionPy, Reemplazo};
use crate::valor::{Mapa, Valor};
use std::ops::ControlFlow;
use std::path::Path;

pub const IGNORADAS: &[&str] = &[
    "__pycache__", "node_modules", "venv", ".venv", "env", ".git", ".github", ".ipynb_checkpoints", "dist", "build",
    ".cache", "site-packages", ".idea", ".vscode", ".gemini", ".mypy_cache", ".pytest_cache", ".tox", "target",
];
pub const MAX_ARCHIVOS: usize = 20000;
pub const MAX_BYTES_BUSQUEDA: u64 = 2 * 1024 * 1024;
pub const MAX_COINCIDENCIAS: usize = 5000;
pub const MAX_RECIENTES: usize = 12;

type R<T> = Result<T, ErrorPy>;

fn es_dir(p: &str) -> bool {
    !p.contains('\0') && Path::new(p).is_dir()
}

fn existe(p: &str) -> bool {
    !p.contains('\0') && Path::new(p).exists()
}

fn es_enlace(p: &str) -> bool {
    std::fs::symlink_metadata(p).map(|m| m.file_type().is_symlink()).unwrap_or(false)
}

// =========================================================================== recorrer

/// `_recorrer`: los archivos como `os.walk` (de arriba abajo, sin seguir enlaces a carpetas), con las carpetas y los
/// nombres ordenados y sin las ignoradas ni las ocultas
fn recorrer(raiz: &str, f: &mut dyn FnMut(String) -> R<ControlFlow<()>>) -> R<ControlFlow<()>> {
    if raiz.is_empty() || raiz.contains('\0') {
        return Ok(ControlFlow::Continue(()));
    }
    let Ok(leidas) = std::fs::read_dir(raiz) else { return Ok(ControlFlow::Continue(())) };
    let mut dirs = Vec::new();
    let mut archivos = Vec::new();
    for e in leidas {
        let Ok(e) = e else { return Ok(ControlFlow::Continue(())) };
        let nombre = e.file_name().to_string_lossy().into_owned();
        // `entry.is_dir()` sigue los enlaces
        let carpeta = match e.file_type() {
            Ok(t) if t.is_symlink() => std::fs::metadata(e.path()).map(|m| m.is_dir()).unwrap_or(false),
            Ok(t) => t.is_dir(),
            Err(_) => false,
        };
        if carpeta {
            dirs.push(nombre);
        } else {
            archivos.push(nombre);
        }
    }
    dirs.retain(|d| !IGNORADAS.contains(&d.as_str()) && !d.starts_with('.'));
    dirs.sort();
    archivos.sort();
    for n in archivos {
        if n.starts_with('.') && n != ".gitignore" && n != ".env.example" {
            continue;
        }
        if f(py::join(raiz, &n))?.is_break() {
            return Ok(ControlFlow::Break(()));
        }
    }
    for d in dirs {
        let nueva = py::join(raiz, &d);
        if es_enlace(&nueva) {
            continue;
        }
        if recorrer(&nueva, f)?.is_break() {
            return Ok(ControlFlow::Break(()));
        }
    }
    Ok(ControlFlow::Continue(()))
}

fn rel(ruta: &str, raiz: &str) -> String {
    py::relpath(ruta, raiz)
}

/// `listar`
pub fn listar(base: &str, limite: usize) -> Mapa {
    let mut salida = Vec::new();
    let mut truncado = false;
    let _ = recorrer(base, &mut |ruta| {
        if salida.len() >= limite {
            truncado = true;
            return Ok(ControlFlow::Break(()));
        }
        let r = rel(&ruta, base);
        salida.push(Valor::Mapa(Mapa::new().con("path", ruta).con("rel", r)));
        Ok(ControlFlow::Continue(()))
    });
    Mapa::new().con("raiz", base).con("archivos", Valor::Lista(salida)).con("truncado", truncado)
}

// =========================================================================== patrones de archivos

fn fnmatch(nombre: &str, patron: &str) -> bool {
    // `fnmatch.fnmatch` en Linux: distingue mayúsculas; `*` casa también con «/»
    fn casa(n: &[char], p: &[char]) -> bool {
        match p.first() {
            None => n.is_empty(),
            Some('*') => (0..=n.len()).any(|i| casa(&n[i..], &p[1..])),
            Some('?') => !n.is_empty() && casa(&n[1..], &p[1..]),
            Some('[') => {
                // una clase: [abc], [!abc], [a-z]; sin «]» de cierre, «[» es literal
                let mut j = 1;
                if p.get(j) == Some(&'!') {
                    j += 1;
                }
                if p.get(j) == Some(&']') {
                    j += 1;
                }
                while j < p.len() && p[j] != ']' {
                    j += 1;
                }
                if j >= p.len() {
                    return n.first() == Some(&'[') && casa(&n[1..], &p[1..]);
                }
                let Some(&c) = n.first() else { return false };
                let clase = &p[1..j];
                let (negada, clase) = match clase.first() {
                    Some('!') => (true, &clase[1..]),
                    _ => (false, clase),
                };
                let mut dentro = false;
                let mut k = 0;
                while k < clase.len() {
                    if k + 2 < clase.len() && clase[k + 1] == '-' {
                        if clase[k] <= c && c <= clase[k + 2] {
                            dentro = true;
                        }
                        k += 3;
                    } else {
                        if clase[k] == c {
                            dentro = true;
                        }
                        k += 1;
                    }
                }
                dentro != negada && casa(&n[1..], &p[j + 1..])
            }
            Some(&x) => n.first() == Some(&x) && casa(&n[1..], &p[1..]),
        }
    }
    let n: Vec<char> = nombre.chars().collect();
    let p: Vec<char> = patron.chars().collect();
    casa(&n, &p)
}

fn coincide_patrones(relativa: &str, incluir: &[String], excluir: &[String]) -> bool {
    let casa = |patron: &str| -> bool {
        let patron = py::strip(patron);
        if patron.is_empty() {
            return false;
        }
        if !patron.contains('/') && !patron.chars().any(|c| "*?[".contains(c)) {
            return relativa.split('/').any(|x| x == patron);
        }
        fnmatch(relativa, patron)
            || fnmatch(&py::basename(relativa), patron)
            || fnmatch(relativa, &format!("*/{patron}"))
            || relativa.starts_with(&format!("{}/", patron.trim_end_matches('/')))
    };
    if !incluir.is_empty() && !incluir.iter().any(|p| casa(p)) {
        return false;
    }
    !excluir.iter().any(|p| casa(p))
}

fn patrones(texto: &str) -> Vec<String> {
    texto.split(',').map(|p| py::strip(p).to_string()).filter(|p| !p.is_empty()).collect()
}

/// `_archivos_texto`: los archivos de texto UTF-8 (sin bytes nulos al principio, de hasta 2 MB) que pasan los filtros
fn archivos_texto(base: &str, incluir: &str, excluir: &str, f: &mut dyn FnMut(String, String, String) -> R<ControlFlow<()>>) -> R<()> {
    let (inc, exc) = (patrones(incluir), patrones(excluir));
    let _fin: ControlFlow<()> = recorrer(base, &mut |ruta| {
        let r = rel(&ruta, base);
        if !coincide_patrones(&r, &inc, &exc) {
            return Ok(ControlFlow::Continue(()));
        }
        let Ok(meta) = std::fs::metadata(&ruta) else { return Ok(ControlFlow::Continue(())) };
        if meta.len() > MAX_BYTES_BUSQUEDA {
            return Ok(ControlFlow::Continue(()));
        }
        let Ok(datos) = std::fs::read(&ruta) else { return Ok(ControlFlow::Continue(())) };
        if datos[..datos.len().min(8192)].contains(&0) {
            return Ok(ControlFlow::Continue(()));
        }
        let Ok(texto) = String::from_utf8(datos) else { return Ok(ControlFlow::Continue(())) };
        f(ruta, r, texto)
    })?;
    Ok(())
}

// =========================================================================== buscar y reemplazar

fn expresion(consulta: &str, regex: bool, mayusculas: bool, palabra: bool) -> R<ExpresionPy> {
    if consulta.is_empty() {
        return Err(ErrorPy::Propia("Escribe qué buscar.".into()));
    }
    if palabra && !regex {
        return ExpresionPy::palabra_literal(consulta, mayusculas)
            .map_err(|e| ErrorPy::Propia(format!("Expresión regular no válida: {e}")));
    }
    let mut patron = if regex { consulta.to_string() } else { regex_py::escapar(consulta) };
    if palabra {
        patron = format!("(?<!\\w){patron}(?!\\w)");
    }
    ExpresionPy::compilar(&patron, mayusculas).map_err(|e| ErrorPy::Propia(format!("Expresión regular no válida: {e}")))
}

fn cortar(t: &str, n: usize) -> String {
    t.chars().take(n).collect()
}

/// `buscar`
#[allow(clippy::too_many_arguments)]
pub fn buscar(
    base: &str,
    consulta: &str,
    regex: bool,
    mayusculas: bool,
    palabra: bool,
    incluir: &str,
    excluir: &str,
    limite: usize,
) -> R<Mapa> {
    let expr = expresion(consulta, regex, mayusculas, palabra)?;
    let mut resultados = Vec::new();
    let (mut total, mut truncado, mut revisados) = (0usize, false, 0usize);
    archivos_texto(base, incluir, excluir, &mut |ruta, r, texto| {
        revisados += 1;
        if !expr.posible(&texto) {
            return Ok(ControlFlow::Continue(()));
        }
        let mut coincidencias = Vec::new();
        'lineas: for (n, linea) in prig_recursos::servidor::lineas_como_python(&texto).into_iter().enumerate() {
            for (ini, fin) in expr.aciertos(linea) {
                if ini == fin {
                    continue;
                }
                let col = linea[..ini].chars().count();
                let col_fin = col + linea[ini..fin].chars().count();
                coincidencias.push(Valor::Mapa(
                    Mapa::new()
                        .con("linea", n + 1)
                        .con("col", col + 1)
                        .con("fin", col_fin + 1)
                        .con("texto", cortar(linea, 400))
                        .con("trozo", cortar(&linea[ini..fin], 200)),
                ));
                total += 1;
                if total >= limite {
                    truncado = true;
                    break 'lineas;
                }
            }
        }
        if !coincidencias.is_empty() {
            resultados.push(Valor::Mapa(Mapa::new().con("path", ruta).con("rel", r).con("coincidencias", Valor::Lista(coincidencias))));
        }
        Ok(if truncado { ControlFlow::Break(()) } else { ControlFlow::Continue(()) })
    })?;
    let archivos = resultados.len();
    Ok(Mapa::new()
        .con("resultados", Valor::Lista(resultados))
        .con("total", total)
        .con("archivos", archivos)
        .con("revisados", revisados)
        .con("truncado", truncado))
}

fn modo(ruta: &str) -> R<u32> {
    use std::os::unix::fs::PermissionsExt;
    std::fs::metadata(ruta).map(|m| m.permissions().mode() & 0o7777).map_err(|e| ErrorPy::os(&e, ruta))
}

/// `reemplazar`: `solo` limita a esas rutas (las que el usuario dejó marcadas)
#[allow(clippy::too_many_arguments)]
pub fn reemplazar(
    base: &str,
    raices: &[String],
    consulta: &str,
    reemplazo: &str,
    regex: bool,
    mayusculas: bool,
    palabra: bool,
    incluir: &str,
    excluir: &str,
    solo: Option<&[String]>,
) -> R<Mapa> {
    let expr = expresion(consulta, regex, mayusculas, palabra)?;
    let permitidas: Option<Vec<String>> = match solo {
        Some(s) => Some(s.iter().map(|p| resolver(p, base, raices).map_err(ErrorPy::Permiso)).collect::<R<_>>()?),
        None => None,
    };
    // Sin regex, el reemplazo es literal: "\\1" o "\\n" no se interpretan. La plantilla se lee en el primer archivo,
    // como `re.subn`
    let plantilla = if regex { Some(regex_py::plantilla(reemplazo, &expr)) } else { None };
    let mut cambiados = Vec::new();
    let mut total = 0usize;
    archivos_texto(base, incluir, excluir, &mut |ruta, r, texto| {
        if let Some(p) = &permitidas {
            if !p.contains(&ruta) {
                return Ok(ControlFlow::Continue(()));
            }
        }
        let rep = match &plantilla {
            None => Reemplazo::Literal(reemplazo.to_string()),
            Some(Ok(_)) => Reemplazo::Plantilla(regex_py::plantilla(reemplazo, &expr).unwrap_or_default()),
            Some(Err(e)) => return Err(ErrorPy::Propia(format!("Reemplazo no válido: {e}"))),
        };
        let (nuevo, n) = expr.subn(&texto, &rep);
        if n > 0 {
            let tmp = format!("{ruta}.prig-tmp");
            std::fs::write(&tmp, &nuevo).map_err(|e| ErrorPy::os(&e, &tmp))?;
            let m = modo(&ruta)?;
            {
                use std::os::unix::fs::PermissionsExt;
                std::fs::set_permissions(&tmp, std::fs::Permissions::from_mode(m)).map_err(|e| ErrorPy::os(&e, &tmp))?;
            }
            std::fs::rename(&tmp, &ruta).map_err(|e| ErrorPy::os2(&e, &tmp, &ruta))?;
            cambiados.push(Valor::Mapa(Mapa::new().con("path", ruta).con("rel", r).con("reemplazos", n)));
            total += n;
        }
        Ok(ControlFlow::Continue(()))
    })?;
    Ok(Mapa::new().con("archivos", Valor::Lista(cambiados)).con("total", total))
}

// =========================================================================== renombrar y duplicar

/// `shutil.copy2`: el contenido, los permisos y las fechas (siguiendo enlaces)
fn copy2(origen: &str, destino: &str) -> R<()> {
    let destino = if es_dir(destino) { py::join(destino, &py::basename(origen)) } else { destino.to_string() };
    std::fs::copy(origen, &destino).map_err(|e| ErrorPy::os(&e, origen))?;
    copiar_fechas(origen, &destino)
}

fn copiar_fechas(origen: &str, destino: &str) -> R<()> {
    use std::os::unix::fs::MetadataExt;
    let m = std::fs::metadata(origen).map_err(|e| ErrorPy::os(&e, origen))?;
    let tiempos = [
        libc::timespec { tv_sec: m.atime() as _, tv_nsec: m.atime_nsec() as _ },
        libc::timespec { tv_sec: m.mtime() as _, tv_nsec: m.mtime_nsec() as _ },
    ];
    let c = std::ffi::CString::new(destino).map_err(|_| ErrorPy::Valor("embedded null byte".into()))?;
    // SAFETY: utimensat lee la ruta y los dos tiempos que se le dan
    unsafe { libc::utimensat(libc::AT_FDCWD, c.as_ptr(), tiempos.as_ptr(), 0) };
    Ok(())
}

/// `shutil.copytree(origen, destino, symlinks=...)`
fn copytree(origen: &str, destino: &str, enlaces: bool) -> R<()> {
    std::fs::create_dir_all(py::dirname(destino)).ok();
    std::fs::create_dir(destino).map_err(|e| ErrorPy::os(&e, destino))?;
    let entradas: Vec<String> = std::fs::read_dir(origen)
        .map_err(|e| ErrorPy::os(&e, origen))?
        .flatten()
        .map(|e| e.file_name().to_string_lossy().into_owned())
        .collect();
    let mut errores = Vec::new();
    for n in entradas {
        let (s, d) = (py::join(origen, &n), py::join(destino, &n));
        let r = if es_enlace(&s) && enlaces {
            std::fs::read_link(&s)
                .and_then(|l| std::os::unix::fs::symlink(l, &d))
                .map_err(|e| ErrorPy::os(&e, &s))
        } else if es_dir(&s) {
            copytree(&s, &d, enlaces)
        } else {
            copy2(&s, &d)
        };
        match r {
            Ok(()) => {}
            // como `errors.extend(err.args[0])`: la lista queda plana
            Err(ErrorPy::Shutil(mas)) => errores.extend(mas),
            Err(e) => errores.push((s, d, e.texto())),
        }
    }
    let _ = copiar_fechas(origen, destino);
    {
        use std::os::unix::fs::PermissionsExt;
        if let Ok(m) = std::fs::metadata(origen) {
            let _ = std::fs::set_permissions(destino, std::fs::Permissions::from_mode(m.permissions().mode() & 0o7777));
        }
    }
    if !errores.is_empty() {
        return Err(ErrorPy::Shutil(errores));
    }
    Ok(())
}

fn rmtree(ruta: &str) -> R<()> {
    std::fs::remove_dir_all(ruta).map_err(|e| ErrorPy::os(&e, ruta))
}

/// `shutil.move`: renombra y, si no se puede (otro disco), copia y borra
fn mover(origen: &str, destino: &str) -> R<()> {
    if std::fs::rename(origen, destino).is_ok() {
        return Ok(());
    }
    if es_enlace(origen) {
        let l = std::fs::read_link(origen).map_err(|e| ErrorPy::os(&e, origen))?;
        std::os::unix::fs::symlink(l, destino).map_err(|e| ErrorPy::os(&e, destino))?;
        return std::fs::remove_file(origen).map_err(|e| ErrorPy::os(&e, origen));
    }
    if es_dir(origen) {
        copytree(origen, destino, true)?;
        rmtree(origen)
    } else {
        copy2(origen, destino)?;
        std::fs::remove_file(origen).map_err(|e| ErrorPy::os(&e, origen))
    }
}

/// `renombrar`: `destino` puede ser un nombre (mismo directorio) o una ruta relativa o absoluta
pub fn renombrar(ruta: &str, destino: &str, base: &str, raices: &[String]) -> R<Mapa> {
    let origen = resolver(ruta, base, raices).map_err(ErrorPy::Permiso)?;
    if !existe(&origen) {
        return Err(ErrorPy::Propia(format!("No existe: {ruta}")));
    }
    if raices.contains(&origen) {
        return Err(ErrorPy::Propia("No se puede renombrar la carpeta raíz del espacio de trabajo.".into()));
    }
    let destino = if !destino.contains('/') { py::join(&py::dirname(&origen), destino) } else { destino.to_string() };
    let final_ = resolver(&destino, base, raices).map_err(ErrorPy::Permiso)?;
    if final_ == origen {
        return Ok(Mapa::new().con("success", true).con("path", final_).con("anterior", origen));
    }
    if existe(&final_) {
        return Err(ErrorPy::Propia(format!("Ya existe: {}", py::relpath(&final_, base))));
    }
    if es_dir(&origen) && format!("{final_}/").starts_with(&format!("{origen}/")) {
        return Err(ErrorPy::Propia("No se puede mover una carpeta dentro de sí misma.".into()));
    }
    py::makedirs_py(&py::dirname(&final_))?;
    mover(&origen, &final_)?;
    let carpeta = es_dir(&final_);
    Ok(Mapa::new().con("success", true).con("path", final_).con("anterior", origen).con("es_dir", carpeta))
}

/// `duplicar`: «nombre copia.ext», «nombre copia 2.ext», ...
pub fn duplicar(ruta: &str, base: &str, raices: &[String]) -> R<Mapa> {
    let origen = resolver(ruta, base, raices).map_err(ErrorPy::Permiso)?;
    if !existe(&origen) {
        return Err(ErrorPy::Propia(format!("No existe: {ruta}")));
    }
    let archivo = !origen.contains('\0') && Path::new(&origen).is_file();
    let (raiz, ext) = if archivo { py::splitext(&origen) } else { (origen.clone(), String::new()) };
    let mut n = 1;
    let candidato = loop {
        let c = format!("{raiz} copia{}{ext}", if n == 1 { String::new() } else { format!(" {n}") });
        if !existe(&c) {
            break c;
        }
        n += 1;
    };
    let final_ = resolver(&candidato, base, raices).map_err(ErrorPy::Permiso)?;
    if es_dir(&origen) {
        copytree(&origen, &final_, false)?;
    } else {
        copy2(&origen, &final_)?;
    }
    Ok(Mapa::new().con("success", true).con("path", final_))
}

// =========================================================================== configuración: recientes y proyectos

/// `_config`: lo que haya en el archivo (cualquier valor de JSON), o `{}` si no se puede leer
fn config(ruta: &str) -> Valor {
    crate::leer_json(Path::new(ruta)).unwrap_or_else(|_| Valor::Mapa(Mapa::new()))
}

/// `_guardar_config`: a un temporal y renombrado; si no se puede, al `.prig_config.json` del directorio actual
fn guardar_config(ruta: &str, datos: &Valor) -> bool {
    let destinos = [ruta.to_string(), py::join(&py::getcwd(), ".prig_config.json")];
    for dest in destinos {
        if py::makedirs(&py::dirname(&abspath(&dest))).is_err() {
            continue;
        }
        let tmp = format!("{dest}.tmp");
        if std::fs::write(&tmp, crate::json::escribir(datos, 2)).is_err() {
            continue;
        }
        if std::fs::rename(&tmp, &dest).is_ok() {
            return true;
        }
    }
    false
}

fn o_lista(v: Valor) -> Valor {
    if v.verdad() {
        v
    } else {
        Valor::Lista(vec![])
    }
}

fn nombre_o_ruta(ruta: &str) -> String {
    let n = py::basename(ruta);
    if n.is_empty() {
        ruta.to_string()
    } else {
        n
    }
}

/// `recientes`
pub fn recientes(cfg: &str, base: &str) -> R<Vec<Valor>> {
    let vistas = o_lista(py::get_py(&config(cfg), "recent_workspaces")?);
    let mut salida = Vec::new();
    for ruta in py::iterar_py(&vistas)? {
        if py::isdir_valor(&ruta)? {
            let r = py::ruta_de(&ruta)?;
            salida.push(Valor::Mapa(Mapa::new().con("path", r).con("name", nombre_o_ruta(r)).con("actual", r == base)));
        }
    }
    Ok(salida)
}

/// `anotar_reciente`
pub fn anotar_reciente(cfg: &str, ruta: &Valor) -> R<()> {
    let mut c = config(cfg);
    let lista: Vec<Valor> =
        py::iterar_py(&o_lista(py::get_py(&c, "recent_workspaces")?))?.into_iter().filter(|r| r != ruta).collect();
    let mut nueva = vec![ruta.clone()];
    nueva.extend(lista.into_iter().take(MAX_RECIENTES - 1));
    py::poner_py(&mut c, "recent_workspaces", Valor::Lista(nueva))?;
    let ultima = py::get_py(&c, "last_workspace")?;
    py::poner_py(&mut c, "last_workspace", if ultima.verdad() { ultima } else { ruta.clone() })?;
    guardar_config(cfg, &c);
    Ok(())
}

/// `olvidar_recientes`
pub fn olvidar_recientes(cfg: &str) -> R<()> {
    let mut c = config(cfg);
    py::poner_py(&mut c, "recent_workspaces", Valor::Lista(vec![]))?;
    guardar_config(cfg, &c);
    Ok(())
}

fn lower(v: &Valor) -> R<String> {
    match v {
        Valor::Texto(t) => Ok(t.to_lowercase()),
        otro => Err(ErrorPy::Atributo(format!("'{}' object has no attribute 'lower'", py::tipo(otro)))),
    }
}

/// `proyectos_guardados`: el actual primero, después los que existen, por nombre
pub fn proyectos_guardados(cfg: &str, base: &str) -> R<Vec<Valor>> {
    let guardados = o_lista(py::get_py(&config(cfg), "saved_projects")?);
    let mut salida: Vec<(Mapa, bool, bool, String)> = Vec::new();
    let mut vistas: Vec<Valor> = Vec::new();
    for p in py::iterar_py(&guardados)? {
        let es_mapa = matches!(p, Valor::Mapa(_));
        let ruta = if es_mapa { py::get_py(&p, "path")? } else { Valor::Texto(p.texto_py()) };
        if !ruta.verdad() {
            continue;
        }
        py::hasheable(&ruta)?;
        if vistas.contains(&ruta) {
            continue;
        }
        vistas.push(ruta.clone());
        let existe = py::isdir_valor(&ruta)?;
        let nombre = if es_mapa { py::get_py(&p, "name")? } else { Valor::Nulo };
        let nombre = if nombre.verdad() {
            nombre
        } else {
            let b = py::basename(py::ruta_de(&ruta)?);
            if b.is_empty() {
                ruta.clone()
            } else {
                Valor::Texto(b)
            }
        };
        let actual = abspath(py::ruta_de(&ruta)?) == abspath(base);
        let creado = if es_mapa { py::get_py(&p, "created_at")? } else { Valor::Nulo };
        let origen = if es_mapa {
            match &p {
                Valor::Mapa(m) => m.get("source").cloned().unwrap_or_else(|| "biblioteca".into()),
                _ => unreachable!(),
            }
        } else {
            "biblioteca".into()
        };
        let m = Mapa::new()
            .con("path", ruta)
            .con("name", nombre.clone())
            .con("exists", existe)
            .con("actual", actual)
            .con("created_at", creado)
            .con("source", origen);
        salida.push((m, actual, existe, String::new()));
    }
    for s in salida.iter_mut() {
        s.3 = lower(s.0.valor("name"))?;
    }
    salida.sort_by(|a, b| (!a.1, !a.2, &a.3).cmp(&(!b.1, !b.2, &b.3)));
    Ok(salida.into_iter().map(|s| Valor::Mapa(s.0)).collect())
}

/// `guardar_proyecto`
pub fn guardar_proyecto(cfg: &str, ruta: &str, nombre: Option<&str>, origen: &Valor) -> R<Mapa> {
    let abs = abspath(&py::expanduser(ruta));
    if !es_dir(&abs) {
        return Err(ErrorPy::Propia(format!("No es una carpeta válida en el sistema: {ruta}")));
    }
    let n = py::strip(nombre.unwrap_or(""));
    let nombre_final = if !n.is_empty() { n.to_string() } else { nombre_o_ruta(&abs) };
    let mut c = config(cfg);
    let guardados = o_lista(py::get_py(&c, "saved_projects")?);
    let ahora = py::ahora_iso();
    let nuevo = Mapa::new()
        .con("path", abs.clone())
        .con("name", nombre_final)
        .con("source", origen.clone())
        .con("created_at", ahora.clone())
        .con("last_opened", ahora);
    let mut encontrado = false;
    let mut nuevos = Vec::new();
    for p in py::iterar_py(&guardados)? {
        let es_mapa = matches!(p, Valor::Mapa(_));
        let p_ruta = if es_mapa { py::get_py(&p, "path")? } else { Valor::Texto(p.texto_py()) };
        if abspath(py::ruta_de(&p_ruta)?) == abs {
            nuevos.push(Valor::Mapa(nuevo.clone()));
            encontrado = true;
        } else if es_mapa {
            nuevos.push(p);
        } else {
            let r = py::ruta_de(&p_ruta)?.to_string();
            nuevos.push(Valor::Mapa(Mapa::new().con("path", r.clone()).con("name", py::basename(&r))));
        }
    }
    if !encontrado {
        nuevos.insert(0, Valor::Mapa(nuevo.clone()));
    }
    py::poner_py(&mut c, "saved_projects", Valor::Lista(nuevos))?;
    guardar_config(cfg, &c);
    Ok(Mapa::new().con("success", true).con("project", nuevo))
}

/// `eliminar_proyecto_guardado`
pub fn eliminar_proyecto(cfg: &str, ruta: &str) -> R<Mapa> {
    let abs = abspath(&py::expanduser(ruta));
    let mut c = config(cfg);
    let guardados = o_lista(py::get_py(&c, "saved_projects")?);
    let mut nuevos = Vec::new();
    for p in py::iterar_py(&guardados)? {
        let r = if matches!(p, Valor::Mapa(_)) { py::get_py(&p, "path")? } else { Valor::Texto(p.texto_py()) };
        if abspath(py::ruta_de(&r)?) != abs {
            nuevos.push(p);
        }
    }
    py::poner_py(&mut c, "saved_projects", Valor::Lista(nuevos))?;
    guardar_config(cfg, &c);
    Ok(Mapa::new().con("success", true).con("path", abs))
}

// =========================================================================== explorar carpetas

/// `listar_directorios`: las subcarpetas de una carpeta, su padre y atajos (Documentos, Descargas, ...)
pub fn listar_directorios(ruta: Option<&str>, base: &str) -> Mapa {
    let casa = py::expanduser("~");
    let mut actual = match ruta {
        Some(r) if !r.is_empty() => abspath(&py::expanduser(r)),
        _ => {
            if es_dir(base) {
                base.to_string()
            } else {
                casa.clone()
            }
        }
    };
    if !es_dir(&actual) {
        actual = casa.clone();
    }
    let mut subcarpetas = Vec::new();
    if let Ok(leidas) = std::fs::read_dir(&actual) {
        let mut entradas: Vec<(String, bool)> = leidas
            .flatten()
            .map(|e| (e.file_name().to_string_lossy().into_owned(), e.file_type().map(|t| t.is_dir()).unwrap_or(false)))
            .collect();
        entradas.sort_by_key(|(n, _)| n.to_lowercase());
        for (n, carpeta) in entradas {
            if carpeta && !n.starts_with('.') && !["__pycache__", "node_modules", ".git", ".venv", "venv"].contains(&n.as_str()) {
                let p = py::join(&actual, &n);
                subcarpetas.push(Valor::Mapa(Mapa::new().con("name", n).con("path", p)));
            }
        }
    }
    let padre = py::dirname(&actual);
    let padre = if padre == actual || !es_dir(&padre) { Valor::Nulo } else { Valor::Texto(padre) };
    let mut atajos: Vec<(String, String, String)> = vec![
        ("Espacio Actual".into(), base.into(), "fa-folder-open".into()),
        ("Carpeta Personal (~)".into(), casa.clone(), "fa-house".into()),
    ];
    let comunes = [
        ("Documentos", py::join(&casa, "Documentos"), "fa-folder"),
        ("Documents", py::join(&casa, "Documents"), "fa-folder"),
        ("Descargas", py::join(&casa, "Descargas"), "fa-download"),
        ("Downloads", py::join(&casa, "Downloads"), "fa-download"),
        ("Escritorio", py::join(&casa, "Escritorio"), "fa-desktop"),
        ("Desktop", py::join(&casa, "Desktop"), "fa-desktop"),
        ("Biblioteca Prig", py::expanduser("~/.prig_books"), "fa-book-bookmark"),
    ];
    for (nom, r, ic) in comunes {
        if es_dir(&r) && !atajos.iter().any(|a| a.1 == r) {
            atajos.push((nom.into(), r, ic.into()));
        }
    }
    let atajos: Vec<Valor> =
        atajos.into_iter().map(|(n, p, i)| Valor::Mapa(Mapa::new().con("name", n).con("path", p).con("icon", i))).collect();
    let nombre = nombre_o_ruta(&actual);
    Mapa::new()
        .con("current", actual.clone())
        .con("current_path", actual)
        .con("current_name", nombre)
        .con("parent", padre.clone())
        .con("parent_path", padre)
        .con("subdirectories", Valor::Lista(subcarpetas))
        .con("shortcuts", Valor::Lista(atajos))
}

// =========================================================================== sistema

fn en_path(programa: &str) -> bool {
    std::env::var("PATH")
        .unwrap_or_default()
        .split(':')
        .any(|d| {
            use std::os::unix::fs::PermissionsExt;
            let p = Path::new(if d.is_empty() { "." } else { d }).join(programa);
            p.metadata().map(|m| m.is_file() && m.permissions().mode() & 0o111 != 0).unwrap_or(false)
        })
}

/// `mostrar_en_sistema`: selecciona el archivo en el explorador (D-Bus) o abre su carpeta (xdg-open)
pub fn mostrar_en_sistema(ruta: &str, base: &str, raices: &[String]) -> R<Mapa> {
    use std::os::unix::process::CommandExt;
    use std::process::{Command, Stdio};
    let destino = resolver(ruta, base, raices).map_err(ErrorPy::Permiso)?;
    if !existe(&destino) {
        return Err(ErrorPy::Propia(format!("No existe: {ruta}")));
    }
    let archivo = Path::new(&destino).is_file();
    let carpeta = if es_dir(&destino) { destino.clone() } else { py::dirname(&destino) };
    if archivo && en_path("dbus-send") {
        let hijo = Command::new("dbus-send")
            .args([
                "--session",
                "--dest=org.freedesktop.FileManager1",
                "--type=method_call",
                "/org/freedesktop/FileManager1",
                "org.freedesktop.FileManager1.ShowItems",
                &format!("array:string:file://{destino}"),
                "string:",
            ])
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn();
        if let Ok(mut h) = hijo {
            let limite = std::time::Instant::now() + std::time::Duration::from_secs(5);
            loop {
                match h.try_wait() {
                    Ok(Some(estado)) => {
                        if estado.success() {
                            return Ok(Mapa::new().con("success", true));
                        }
                        break;
                    }
                    Ok(None) if std::time::Instant::now() < limite => std::thread::sleep(std::time::Duration::from_millis(20)),
                    _ => {
                        let _ = h.kill();
                        let _ = h.wait();
                        return Err(ErrorPy::OsTexto("Command 'dbus-send' timed out after 5 seconds".into()));
                    }
                }
            }
        }
    }
    let mut cmd = Command::new("xdg-open");
    cmd.arg(&carpeta).stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
    // SAFETY: setsid() en el hijo, antes de exec (start_new_session=True)
    unsafe {
        cmd.pre_exec(|| {
            libc::setsid();
            Ok(())
        });
    }
    match cmd.spawn() {
        Ok(mut h) => {
            // que no quede un proceso zombi
            std::thread::spawn(move || {
                let _ = h.wait();
            });
            Ok(Mapa::new().con("success", true))
        }
        Err(_) => Err(ErrorPy::Propia("No se encontró un explorador de archivos en el sistema.".into())),
    }
}
