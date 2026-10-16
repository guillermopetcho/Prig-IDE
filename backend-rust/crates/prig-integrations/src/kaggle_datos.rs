//! Los datos de Kaggle en el proyecto (`kaggle_explorar.py`, la parte sin red): lo descargado en `kaggle_datos/`, la
//! vista previa de una tabla (como el «Data Explorer» de Kaggle) y las rutas de los notebooks. La vista previa adivina
//! el separador con `csv.Sniffer` y lee el CSV con el dialecto «excel» del módulo `csv`: los dos están portados aquí
//! paso a paso, para que las filas, los tipos y las estadísticas salgan iguales.

use crate::kaggle::{self, ErrorKaggle, Fallo};
use prig_plataforma::valor::{redondear, Mapa, Valor};
use std::path::{Path, PathBuf};
use std::sync::LazyLock;

pub const CARPETA_DATOS: &str = "kaggle_datos";
const LIMITE_PREVIA: usize = 20000;
const VACIOS: [&str; 8] = ["", "NA", "N/A", "NaN", "nan", "null", "NULL", "None"];
/// `csv.field_size_limit()` por defecto
const LIMITE_CAMPO: usize = 131072;

// ---------------------------------------------------------------------------------------------- csv.Sniffer

/// `max(d, key=d.get)`: la primera clave con el valor más alto (en orden de inserción)
fn max_por_valor<K: Clone>(d: &[(K, i64)]) -> Option<K> {
    let mut mejor: Option<&(K, i64)> = None;
    for x in d {
        if mejor.is_none_or(|m| x.1 > m.1) {
            mejor = Some(x);
        }
    }
    mejor.map(|m| m.0.clone())
}

fn sumar<K: PartialEq>(d: &mut Vec<(K, i64)>, k: K) {
    match d.iter_mut().find(|x| x.0 == k) {
        Some(x) => x.1 += 1,
        None => d.push((k, 1)),
    }
}

static PATRONES_COMILLAS: LazyLock<Vec<fancy_regex::Regex>> = LazyLock::new(|| {
    [
        r#"(?sm)(?P<delim>[^\w\n"'])(?P<space> ?)(?P<quote>["']).*?(?P=quote)(?P=delim)"#,
        r#"(?sm)(?:^|\n)(?P<quote>["']).*?(?P=quote)(?P<delim>[^\w\n"'])(?P<space> ?)"#,
        r#"(?sm)(?P<delim>[^\w\n"'])(?P<space> ?)(?P<quote>["']).*?(?P=quote)(?:$|\n)"#,
        r#"(?sm)(?:^|\n)(?P<quote>["']).*?(?P=quote)(?:$|\n)"#,
    ]
    .iter()
    .map(|p| fancy_regex::Regex::new(p).expect("patrón del Sniffer"))
    .collect()
});

/// `_guess_quote_and_delimiter`: el separador junto a texto entre comillas (None si no hay comillas así)
fn separador_por_comillas(datos: &str, delimitadores: &str) -> Option<String> {
    for re in PATRONES_COMILLAS.iter() {
        let encontrados: Vec<_> = re.captures_iter(datos).flatten().collect();
        if encontrados.is_empty() {
            continue;
        }
        let tiene_delim = re.capture_names().any(|n| n == Some("delim"));
        let mut delims: Vec<(String, i64)> = Vec::new();
        for m in &encontrados {
            if !tiene_delim {
                continue;
            }
            let k = m.name("delim").map(|x| x.as_str()).unwrap_or("");
            if !k.is_empty() && delimitadores.contains(k) {
                sumar(&mut delims, k.to_string());
            }
        }
        let delim = match max_por_valor(&delims) {
            Some(d) if d == "\n" => String::new(),
            Some(d) => d,
            None => String::new(),
        };
        return Some(delim);
    }
    None
}

/// `_guess_delimiter`: el carácter que aparece el mismo número de veces en (casi) todas las líneas
fn separador_por_frecuencia(datos: &str, delimitadores: &str) -> String {
    let lineas: Vec<&str> = datos.split('\n').filter(|l| !l.is_empty()).collect();
    let ascii: Vec<char> = (0u8..127).map(|c| c as char).collect();
    let largo_trozo = lineas.len().min(10);
    let mut iteracion = 0usize;
    // char -> [(frecuencia, filas)] en orden de inserción
    let mut frecuencias: Vec<Vec<(usize, i64)>> = vec![Vec::new(); ascii.len()];
    let mut vistos = vec![false; ascii.len()];
    let mut modos: Vec<(char, (usize, i64))> = Vec::new();
    let mut delims: Vec<(char, (usize, i64))> = Vec::new();
    let (mut inicio, mut fin) = (0usize, largo_trozo);
    let preferidos = [',', '\t', ';', ' ', ':'];
    let cuenta = |l: &str, c: char| l.chars().filter(|x| *x == c).count();
    let espacio_inicial = |_d: char| {};
    let _ = espacio_inicial;
    while inicio < lineas.len() {
        iteracion += 1;
        for l in &lineas[inicio..fin.min(lineas.len())] {
            for (i, &c) in ascii.iter().enumerate() {
                let f = cuenta(l, c);
                vistos[i] = true;
                match frecuencias[i].iter_mut().find(|x| x.0 == f) {
                    Some(x) => x.1 += 1,
                    None => frecuencias[i].push((f, 1)),
                }
            }
        }
        for (i, &c) in ascii.iter().enumerate() {
            if !vistos[i] {
                continue;
            }
            let items = &frecuencias[i];
            if items.len() == 1 && items[0].0 == 0 {
                continue;
            }
            let modo = if items.len() > 1 {
                let mut m = items[0];
                for x in items {
                    if x.1 > m.1 {
                        m = *x;
                    }
                }
                let pos = items.iter().position(|x| *x == m).unwrap_or(0);
                let resto: i64 = items.iter().enumerate().filter(|(j, _)| *j != pos).map(|(_, x)| x.1).sum();
                (m.0, m.1 - resto)
            } else {
                items[0]
            };
            match modos.iter_mut().find(|x| x.0 == c) {
                Some(x) => x.1 = modo,
                None => modos.push((c, modo)),
            }
        }
        let total = (largo_trozo * iteracion).min(lineas.len()) as f64;
        let mut consistencia = 1.0f64;
        while delims.is_empty() && consistencia >= 0.9 {
            for (k, v) in &modos {
                if v.0 > 0 && v.1 > 0 && (v.1 as f64 / total) >= consistencia && delimitadores.contains(*k) {
                    delims.push((*k, *v));
                }
            }
            consistencia -= 0.01;
        }
        if delims.len() == 1 {
            return delims[0].0.to_string();
        }
        inicio = fin;
        fin += largo_trozo;
        if largo_trozo == 0 {
            break;
        }
    }
    if delims.is_empty() {
        return String::new();
    }
    if delims.len() > 1 {
        for d in preferidos {
            if delims.iter().any(|x| x.0 == d) {
                return d.to_string();
            }
        }
    }
    let mut items: Vec<((usize, i64), char)> = delims.iter().map(|(k, v)| (*v, *k)).collect();
    items.sort();
    items.last().map(|x| x.1.to_string()).unwrap_or_default()
}

/// `csv.Sniffer().sniff(muestra, delimiters=",;\t|").delimiter`, o «,» si no lo adivina (`csv.Error`)
pub fn adivinar_separador(muestra: &str) -> char {
    let delimitadores = ",;\t|";
    let d = match separador_por_comillas(muestra, delimitadores) {
        Some(d) if !d.is_empty() => d,
        _ => separador_por_frecuencia(muestra, delimitadores),
    };
    d.chars().next().unwrap_or(',')
}

// ---------------------------------------------------------------------------------------------- csv.reader

/// `csv.reader(f, delimiter=sep)` con el dialecto «excel» (comillas «"» dobladas, sin escape, no estricto) sobre un
/// archivo abierto con `newline=""`: la máquina de estados de `_csv.c`, línea a línea (las líneas terminan en «\n»,
/// «\r\n» o «\r» y cada una se cierra con el marcador EOL)
pub struct LectorCsv {
    lineas: std::vec::IntoIter<Vec<char>>,
    sep: char,
}

#[derive(PartialEq, Clone, Copy)]
enum E {
    InicioFila,
    InicioCampo,
    Campo,
    Comillas,
    ComillaEnComillas,
    ComerCrNl,
}

impl LectorCsv {
    pub fn new(texto: &str, sep: char) -> LectorCsv {
        let mut lineas = Vec::new();
        let mut actual = Vec::new();
        let mut it = texto.chars().peekable();
        while let Some(c) = it.next() {
            actual.push(c);
            if c == '\n' {
                lineas.push(std::mem::take(&mut actual));
            } else if c == '\r' {
                if it.peek() == Some(&'\n') {
                    actual.push('\n');
                    it.next();
                }
                lineas.push(std::mem::take(&mut actual));
            }
        }
        if !actual.is_empty() {
            lineas.push(actual);
        }
        LectorCsv { lineas: lineas.into_iter(), sep }
    }

    /// La siguiente fila (None al terminar; Err si un campo pasa del límite de `csv`)
    pub fn fila(&mut self) -> Option<Result<Vec<String>, String>> {
        let mut fila: Vec<String> = Vec::new();
        let mut campo = String::new();
        let mut largo = 0usize;
        let mut e = E::InicioFila;
        loop {
            let Some(linea) = self.lineas.next() else {
                if e == E::InicioFila {
                    return None;
                }
                // fin de los datos dentro de un campo (no estricto: se cierra la fila)
                if largo != 0 || e == E::Comillas {
                    fila.push(campo);
                }
                return Some(Ok(fila));
            };
            // cada carácter y, al final, el marcador de fin de línea (None)
            for c in linea.into_iter().map(Some).chain(std::iter::once(None)) {
                let fin_linea = |c: Option<char>| matches!(c, None | Some('\n') | Some('\r'));
                let guardar = |fila: &mut Vec<String>, campo: &mut String, largo: &mut usize| {
                    fila.push(std::mem::take(campo));
                    *largo = 0;
                };
                macro_rules! anadir {
                    ($ch:expr) => {{
                        if largo >= LIMITE_CAMPO {
                            return Some(Err(format!("field larger than field limit ({LIMITE_CAMPO})")));
                        }
                        campo.push($ch);
                        largo += 1;
                    }};
                }
                let mut estado = e;
                loop {
                    match estado {
                        E::InicioFila => {
                            if c.is_none() {
                                return Some(Ok(fila));
                            } else if fin_linea(c) {
                                e = E::ComerCrNl;
                            } else {
                                estado = E::InicioCampo;
                                continue;
                            }
                        }
                        E::InicioCampo => {
                            if fin_linea(c) {
                                guardar(&mut fila, &mut campo, &mut largo);
                                e = if c.is_none() { E::InicioFila } else { E::ComerCrNl };
                            } else if c == Some('"') {
                                e = E::Comillas;
                            } else if c == Some(self.sep) {
                                guardar(&mut fila, &mut campo, &mut largo);
                                e = E::InicioCampo;
                            } else {
                                anadir!(c.unwrap());
                                e = E::Campo;
                            }
                        }
                        E::Campo => {
                            if fin_linea(c) {
                                guardar(&mut fila, &mut campo, &mut largo);
                                e = if c.is_none() { E::InicioFila } else { E::ComerCrNl };
                            } else if c == Some(self.sep) {
                                guardar(&mut fila, &mut campo, &mut largo);
                                e = E::InicioCampo;
                            } else {
                                anadir!(c.unwrap());
                                e = E::Campo;
                            }
                        }
                        E::Comillas => {
                            if c.is_none() {
                                e = E::Comillas;
                            } else if c == Some('"') {
                                e = E::ComillaEnComillas;
                            } else {
                                anadir!(c.unwrap());
                                e = E::Comillas;
                            }
                        }
                        E::ComillaEnComillas => {
                            if c == Some('"') {
                                anadir!('"');
                                e = E::Comillas;
                            } else if c == Some(self.sep) {
                                guardar(&mut fila, &mut campo, &mut largo);
                                e = E::InicioCampo;
                            } else if fin_linea(c) {
                                guardar(&mut fila, &mut campo, &mut largo);
                                e = if c.is_none() { E::InicioFila } else { E::ComerCrNl };
                            } else {
                                anadir!(c.unwrap());
                                e = E::Campo;
                            }
                        }
                        E::ComerCrNl => {
                            if c.is_none() {
                                e = E::InicioFila;
                            } else if fin_linea(c) {
                                e = E::ComerCrNl;
                            } else {
                                return Some(Err("new-line character seen in unquoted field".into()));
                            }
                        }
                    }
                    break;
                }
                let _ = estado;
                if e == E::InicioFila && c.is_none() {
                    return Some(Ok(fila));
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------------------------- vista previa

fn numero(v: &str) -> Option<f64> {
    if ["", "NA", "NaN", "nan", "null", "None"].contains(&v) {
        return None;
    }
    // «inf» o «nan» cuentan como texto: un infinito en las estadísticas rompía la respuesta (JSON no los admite)
    prig_plataforma::valor::real_de_texto(&v.replace(',', "")).filter(|x| x.is_finite())
}

/// `os.path.realpath(ruta)` dentro de `<espacio>/kaggle_datos` y que sea un archivo
fn dentro_de_datos(ruta: &str, espacio: &Path) -> Option<PathBuf> {
    let raiz = std::fs::canonicalize(espacio.join(CARPETA_DATOS)).ok()?;
    let real = std::fs::canonicalize(ruta).ok()?;
    (real.starts_with(&raiz) && real != raiz && real.is_file()).then_some(real)
}

/// `GET /api/kaggle/archivo`: una imagen de los datos descargados (None = 404)
pub fn imagen(ruta: &str, espacio: &Path) -> Option<PathBuf> {
    let r = dentro_de_datos(ruta, espacio)?;
    let n = r.to_string_lossy().to_lowercase();
    [".png", ".jpg", ".jpeg", ".gif", ".webp"].iter().any(|e| n.ends_with(e)).then_some(r)
}

/// `read(n)` de texto (`errors="replace"`): los primeros `n` caracteres
fn leer_caracteres(ruta: &Path, n: usize) -> std::io::Result<String> {
    let b = std::fs::read(ruta)?;
    Ok(String::from_utf8_lossy(&b).chars().take(n).collect())
}

/// `vista_previa(ruta, workspace, filas)`
pub fn vista_previa(ruta: &str, espacio: &Path, filas: usize) -> Result<Mapa, Fallo> {
    let Some(real) = dentro_de_datos(ruta, espacio) else {
        return Err(ErrorKaggle("Ese archivo no está entre los datos descargados.".into()).into());
    };
    let nombre = real.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
    let ext = if nombre.contains('.') { nombre.to_lowercase().rsplit('.').next().unwrap_or("").to_string() } else { String::new() };
    let bytes = std::fs::metadata(&real).map(|m| m.len()).unwrap_or(0);
    let base = Mapa::new().con("nombre", nombre).con("bytes", bytes as i128).con("tipo", ext.clone());
    Ok(match ext.as_str() {
        "csv" | "tsv" => base.fusion(&resumen_csv(&real, if ext == "tsv" { Some('\t') } else { None }, filas)?),
        "json" | "txt" | "md" | "geojson" => base.con("texto", leer_caracteres(&real, 6000).map_err(|_| Fallo::Interno)?),
        "png" | "jpg" | "jpeg" | "gif" | "webp" => base.con("imagen", true),
        _ => base.con("nota", "Sin vista previa para este tipo de archivo."),
    })
}

struct Columna {
    nombre: String,
    faltan: usize,
    numeros: usize,
    valores: Vec<(String, i64)>,
    min: Option<f64>,
    max: Option<f64>,
    suma: f64,
}

/// `_resumen_csv`
fn resumen_csv(ruta: &Path, separador: Option<char>, filas: usize) -> Result<Mapa, Fallo> {
    let b = std::fs::read(ruta).map_err(|_| Fallo::Interno)?;
    let texto = String::from_utf8_lossy(&b);
    let sep = separador.unwrap_or_else(|| adivinar_separador(&texto.chars().take(20000).collect::<String>()));
    let mut lector = LectorCsv::new(&texto, sep);
    let cabecera = match lector.fila() {
        None => Vec::new(),
        Some(r) => r.map_err(|_| Fallo::Interno)?,
    };
    let mut cols: Vec<Columna> = cabecera
        .iter()
        .map(|c| Columna { nombre: c.clone(), faltan: 0, numeros: 0, valores: Vec::new(), min: None, max: None, suma: 0.0 })
        .collect();
    let mut primeras = Vec::new();
    let mut leidas = 0usize;
    while let Some(fila) = lector.fila() {
        let fila = fila.map_err(|_| Fallo::Interno)?;
        if leidas < filas {
            primeras.push(Valor::Lista(fila.iter().take(cabecera.len()).cloned().map(Valor::Texto).collect()));
        }
        if leidas < LIMITE_PREVIA {
            for (i, c) in cols.iter_mut().enumerate() {
                let v = fila.get(i).map(|x| prig_plataforma::py::strip(x).to_string()).unwrap_or_default();
                if VACIOS.contains(&v.as_str()) {
                    c.faltan += 1;
                    continue;
                }
                if let Some(n) = numero(&v) {
                    c.numeros += 1;
                    c.suma += n;
                    c.min = Some(match c.min {
                        Some(m) if !(n < m) => m,
                        _ => n,
                    });
                    c.max = Some(match c.max {
                        Some(m) if !(n > m) => m,
                        _ => n,
                    });
                }
                if c.valores.len() <= 1000 {
                    sumar(&mut c.valores, v);
                }
            }
        }
        leidas += 1;
    }
    let analizadas = leidas.min(LIMITE_PREVIA);
    let mut columnas = Vec::new();
    for c in &cols {
        let presentes = analizadas as i64 - c.faltan as i64;
        let numerica = presentes > 0 && c.numeros as f64 >= presentes as f64 * 0.95;
        let mut frecuentes = c.valores.clone();
        frecuentes.sort_by_key(|x| -x.1);
        frecuentes.truncate(5);
        let distintos = if c.valores.len() <= 1000 { Valor::Entero(c.valores.len() as i128) } else { Valor::Texto("más de 1000".into()) };
        let sin_frecuentes = (numerica && c.valores.len() > 20) || (presentes > 20 && c.valores.len() as f64 > presentes as f64 * 0.9);
        let real = |x: Option<f64>| x.map(Valor::Real).unwrap_or(Valor::Nulo);
        columnas.push(Valor::Mapa(
            Mapa::new()
                .con("nombre", c.nombre.clone())
                .con("tipo", if numerica { "número" } else { "texto" })
                .con("faltan", c.faltan as i128)
                .con("faltan_pct", if analizadas > 0 { Valor::Real(redondear(100.0 * c.faltan as f64 / analizadas as f64, 1)) } else { Valor::Entero(0) })
                .con("distintos", distintos)
                .con("min", if numerica { real(c.min) } else { Valor::Nulo })
                .con("max", if numerica { real(c.max) } else { Valor::Nulo })
                .con("media", if numerica && c.numeros > 0 { Valor::Real(redondear(c.suma / c.numeros as f64, 4)) } else { Valor::Nulo })
                .con(
                    "frecuentes",
                    Valor::Lista(if sin_frecuentes {
                        Vec::new()
                    } else {
                        frecuentes
                            .into_iter()
                            .map(|(v, n)| Valor::Mapa(Mapa::new().con("valor", v.chars().take(60).collect::<String>()).con("veces", n as i128)))
                            .collect()
                    }),
                ),
        ));
    }
    Ok(Mapa::new()
        .con("separador", sep.to_string())
        .con("columnas", Valor::Lista(columnas))
        .con("filas", Valor::Lista(primeras))
        .con("total_filas", leidas as i128)
        .con("analizadas", analizadas as i128))
}

// ---------------------------------------------------------------------------------------------- lo descargado

/// `os.walk(raiz)`: (carpeta, archivos) en el orden del sistema (sin seguir enlaces a carpetas)
fn recorrer(raiz: &Path) -> Vec<(PathBuf, Vec<String>)> {
    let mut salida = Vec::new();
    let mut pila = vec![raiz.to_path_buf()];
    while let Some(d) = pila.pop() {
        let Ok(l) = std::fs::read_dir(&d) else { continue };
        let mut carpetas = Vec::new();
        let mut archivos = Vec::new();
        for e in l.flatten() {
            let n = e.file_name().to_string_lossy().into_owned();
            if e.path().is_dir() {
                if !e.file_type().is_ok_and(|t| t.is_symlink()) {
                    carpetas.push(e.path());
                }
            } else {
                archivos.push(n);
            }
        }
        salida.push((d, archivos));
        // os.walk baja en el orden de la lista: se apilan al revés
        for c in carpetas.into_iter().rev() {
            pila.push(c);
        }
    }
    salida
}

fn relativa(ruta: &Path, base: &Path) -> String {
    prig_plataforma::py::relpath(&ruta.to_string_lossy(), &base.to_string_lossy())
}

/// `_nombre_local`: como el punto de montaje de Kaggle, /kaggle/input/<slug>
pub fn nombre_local(r: &str) -> String {
    r.rsplit('/').next().unwrap_or(r).to_string()
}

/// `local(tipo, ref, workspace)`: qué hay ya descargado en el proyecto
pub fn local(r: &str, espacio: &Path) -> Result<Option<Mapa>, Fallo> {
    let raiz = espacio.join(CARPETA_DATOS).join(nombre_local(r));
    if !raiz.is_dir() {
        return Ok(None);
    }
    let mut archivos = Vec::new();
    let mut total: u64 = 0;
    for (base, mut nombres) in recorrer(&raiz) {
        nombres.sort();
        for n in nombres {
            let ruta = base.join(&n);
            let b = std::fs::metadata(&ruta).map_err(|_| Fallo::Interno)?.len();
            total += b;
            archivos.push(Valor::Mapa(Mapa::new().con("ruta", ruta.to_string_lossy().into_owned()).con("relativa", relativa(&ruta, &raiz)).con("bytes", b as i128)));
            if archivos.len() >= 500 {
                break;
            }
        }
    }
    Ok(Some(
        Mapa::new()
            .con("carpeta", raiz.to_string_lossy().into_owned())
            .con("relativa", relativa(&raiz, espacio))
            .con("archivos", Valor::Lista(archivos))
            .con("bytes", total as i128),
    ))
}

/// `mis_datos(workspace)`: lo descargado en el proyecto, lo más reciente primero
pub fn mis_datos(espacio: &Path) -> Result<Vec<Mapa>, Fallo> {
    let registro = kaggle::leer_objeto(&kaggle::carpeta().join("descargas.json")).unwrap_or_default();
    let raiz = espacio.join(CARPETA_DATOS);
    let mut nombres: Vec<String> = match std::fs::read_dir(&raiz) {
        Ok(l) if raiz.is_dir() => l.flatten().map(|e| e.file_name().to_string_lossy().into_owned()).collect(),
        _ => Vec::new(),
    };
    nombres.sort();
    let mut salida = Vec::new();
    for nombre in nombres {
        let carpeta = raiz.join(&nombre);
        if !carpeta.is_dir() {
            continue;
        }
        let r = match registro.get(&carpeta.to_string_lossy().into_owned()) {
            Some(Valor::Mapa(m)) => m.clone(),
            None => Mapa::new(),
            Some(v) if !v.verdad() => Mapa::new(),
            Some(_) => return Err(Fallo::Interno),
        };
        let tipo = r.get("tipo").cloned().unwrap_or(Valor::Nulo);
        let referencia = match r.get("ref") {
            Some(v) if v.verdad() => v.clone(),
            _ => Valor::Texto(nombre.clone()),
        };
        let info = if tipo.verdad() { local(&referencia.texto_py(), espacio)? } else { None };
        let info = match info {
            Some(i) => i,
            None => {
                let mut archivos = Vec::new();
                let mut total = 0u64;
                for (base, ns) in recorrer(&carpeta) {
                    for n in ns {
                        let ruta = base.join(&n);
                        let b = std::fs::metadata(&ruta).map_err(|_| Fallo::Interno)?.len();
                        total += b;
                        if archivos.len() < 500 {
                            archivos.push(Valor::Mapa(Mapa::new().con("ruta", ruta.to_string_lossy().into_owned()).con("relativa", relativa(&ruta, &carpeta)).con("bytes", b as i128)));
                        }
                    }
                }
                Mapa::new()
                    .con("carpeta", carpeta.to_string_lossy().into_owned())
                    .con("relativa", relativa(&carpeta, espacio))
                    .con("bytes", total as i128)
                    .con("archivos", Valor::Lista(archivos))
            }
        };
        let mut m = Mapa::new().con("nombre", nombre).con("tipo", tipo).con("ref", referencia).con("fecha", r.get("fecha").cloned().unwrap_or(Valor::Nulo));
        for (k, v) in info.iter() {
            m.poner(k.clone(), v.clone());
        }
        salida.push(m);
    }
    salida.sort_by_key(|m| std::cmp::Reverse(m.texto("fecha").unwrap_or_default().to_string()));
    Ok(salida)
}
