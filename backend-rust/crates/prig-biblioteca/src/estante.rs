//! El estante de la biblioteca (`~/.prig_books`): los elementos que se ven (`BookService.list_books`), los que el
//! usuario quitó de la vista y lo que Prig guarda de cada uno.
//!
//! **Quitar no borra archivos del usuario.** Un elemento quitado deja de verse (y de indexarse) y queda en
//! `.index/ocultos.json`, de donde se puede volver a poner. Lo que sí se puede borrar, eligiendo pieza a pieza, es lo
//! que Prig generó sobre él: la ficha de IA, las citas, las páginas corregidas, los recortes, sus fragmentos en el
//! índice de búsqueda (`catalog.db`) y lo que aprendió de él la base de conocimiento (`knowledge.db`). En una carpeta,
//! además, se puede quitar solo parte de lo que contiene.

use prig_plataforma::py::{abspath, basename, isabs, join, relpath, splitext};
use prig_plataforma::valor::{redondear, Mapa, Valor};
use rusqlite::{params, Connection, OpenFlags};
use std::collections::{BTreeSet, HashSet};
use std::path::{Path, PathBuf};

/// Lo que la biblioteca muestra (superconjunto de lo que se indexa)
pub const VISIBLES: &[&str] = &["pdf", "md", "txt", "rst", "ipynb", "py", "js", "sql", "json", "html", "css", "cpp", "c", "csv", "tsv", "parquet"];
/// Lo que el motor de conocimiento sabe trocear e indexar
pub const INDEXABLES: &[&str] = &["pdf", "md", "txt", "rst", "ipynb", "py", "js", "sql"];
/// Las carpetas de categoría, en el orden de `CATEGORIES`
pub const CATEGORIAS: &[&str] = &["books", "documentation", "papers", "code", "notebooks", "datasets", "projects"];

/// Carpetas de la raíz que son de Prig: citas, trabajos exportados, el analista de librerías y los paquetes
pub const INFRAESTRUCTURA: &[&str] = &["metadata", ".index", "citas", "jobs", "librerias", "packs"];

/// Las piezas que Prig guarda de un elemento y que se pueden borrar por separado
pub const PIEZAS: &[(&str, &str, &str)] = &[
    ("ficha", "Ficha de IA", "El análisis del modelo: resumen, temas, conceptos, nivel."),
    ("citas", "Citas y notas", "Las citas que guardaste con su página, capítulo, nota y etiquetas."),
    ("ediciones", "Páginas corregidas", "El texto de las páginas que corregiste a mano en el lector."),
    ("recortes", "Recortes", "Los recortes de página que guardaste para citar."),
    ("indice", "Índice de búsqueda", "Los fragmentos con los que el tutor busca y cita este elemento."),
    ("conocimiento", "Base de conocimiento", "Conceptos, afirmaciones, capítulos, figuras y preguntas aprendidos del libro, y su ficha de lectura."),
];

/// `os.path.splitext(nombre)[1]` sin el punto, en minúsculas
fn ext_de(nombre: &str) -> String {
    splitext(nombre).1.trim_start_matches('.').to_lowercase()
}

/// `_fallback_title`: un título legible a partir del nombre
pub fn titulo_de_nombre(nombre: &str) -> String {
    let raiz = match nombre.rfind('.') {
        Some(i) => &nombre[..i],
        None => nombre,
    };
    let t = prig_plataforma::py::strip(&raiz.replace(['_', '-'], " ")).to_string();
    if t.is_empty() { nombre.to_string() } else { t }
}

/// `detect_category`
pub fn categoria_de(ruta: &str) -> &'static str {
    if Path::new(ruta).is_dir() {
        return "projects";
    }
    let nombre = basename(ruta).to_lowercase();
    let ext = ext_de(ruta);
    if nombre.contains("paper") || nombre.contains("arxiv") || nombre.contains("biorxiv") {
        "papers"
    } else if ext == "pdf" {
        "books"
    } else if ext == "ipynb" {
        "notebooks"
    } else if ["py", "js", "cpp", "c", "rs", "go", "html", "css"].contains(&ext.as_str()) {
        "code"
    } else if ["csv", "parquet", "tsv"].contains(&ext.as_str()) {
        "datasets"
    } else if ["md", "txt", "rst"].contains(&ext.as_str()) {
        "documentation"
    } else {
        "books"
    }
}

fn leer_json(ruta: &Path) -> Option<Valor> {
    prig_plataforma::json::leer(&std::fs::read_to_string(ruta).ok()?).ok()
}

/// Escribe un JSON como `json.dump(..., indent=2, ensure_ascii=False)`, de una vez (archivo temporal y rename)
fn escribir_json(ruta: &Path, v: &Valor) -> std::io::Result<()> {
    if let Some(p) = ruta.parent() {
        std::fs::create_dir_all(p)?;
    }
    let tmp = ruta.with_extension("json.tmp");
    std::fs::write(&tmp, prig_plataforma::json::escribir(v, 2))?;
    std::fs::rename(&tmp, ruta)
}

/// ¿`ruta` es `base` o está dentro?
fn dentro(ruta: &str, base: &str) -> bool {
    ruta == base || ruta.strip_prefix(base).is_some_and(|r| r.starts_with('/'))
}

pub struct Estante {
    pub raiz: String,
}

/// Un elemento del estante con su ruta absoluta y si es un proyecto guardado (fuera de la biblioteca)
#[derive(Clone, Debug)]
pub struct Elemento {
    pub ruta: String,
    pub proyecto: bool,
}

impl Estante {
    /// La biblioteca de Python: `PRIG_BOOKS_DIR` o `~/.prig_books`
    pub fn por_defecto() -> Estante {
        let raiz = std::env::var("PRIG_BOOKS_DIR").ok().filter(|r| !r.is_empty()).unwrap_or_else(|| prig_plataforma::py::expanduser("~/.prig_books"));
        Estante { raiz: abspath(&raiz) }
    }

    pub fn new(raiz: &str) -> Estante {
        Estante { raiz: abspath(raiz) }
    }

    fn en(&self, rel: &str) -> PathBuf {
        PathBuf::from(join(&self.raiz, rel))
    }
    fn indice(&self) -> PathBuf {
        self.en(".index")
    }
    fn archivo_ocultos(&self) -> PathBuf {
        self.indice().join("ocultos.json")
    }
    fn archivo_recortes(&self) -> PathBuf {
        match std::env::var("PRIG_SNIPPETS_FILE") {
            Ok(r) if !r.is_empty() => PathBuf::from(r),
            _ => self.en("snippets.json"),
        }
    }

    // ------------------------------------------------------------------------------------------ ocultos

    /// Lo que el usuario quitó de la vista: `[{ruta, titulo, categoria, proyecto, quitado_en}]`
    pub fn ocultos(&self) -> Vec<Mapa> {
        match leer_json(&self.archivo_ocultos()) {
            Some(Valor::Mapa(m)) => match m.get("ocultos") {
                Some(Valor::Lista(l)) => l.iter().filter_map(|x| if let Valor::Mapa(m) = x { Some(m.clone()) } else { None }).collect(),
                _ => Vec::new(),
            },
            _ => Vec::new(),
        }
    }

    fn guardar_ocultos(&self, l: Vec<Mapa>) -> std::io::Result<()> {
        let doc = Mapa::new()
            .con("version", 1)
            .con("nota", "Elementos quitados de la biblioteca de Prig. Sus archivos siguen en su sitio; quitar una línea vuelve a mostrarlo.")
            .con("ocultos", Valor::Lista(l.into_iter().map(Valor::Mapa).collect()));
        escribir_json(&self.archivo_ocultos(), &Valor::Mapa(doc))
    }

    /// ¿Está oculto `ruta` o algo que lo contiene?
    pub fn oculto(ruta: &str, ocultos: &[String]) -> bool {
        ocultos.iter().any(|o| dentro(ruta, o))
    }

    pub fn rutas_ocultas(&self) -> Vec<String> {
        self.ocultos().iter().filter_map(|m| m.texto("ruta").map(String::from)).collect()
    }

    fn ocultar(&self, e: &Elemento, titulo: &str) -> std::io::Result<()> {
        let mut l = self.ocultos();
        l.retain(|m| m.texto("ruta") != Some(e.ruta.as_str()));
        let categoria = if e.proyecto { "projects" } else { self.categoria_de_ruta(&e.ruta) };
        l.push(
            Mapa::new()
                .con("ruta", e.ruta.clone())
                .con("titulo", titulo)
                .con("categoria", categoria)
                .con("proyecto", e.proyecto)
                .con("quitado_en", prig_plataforma::py::ahora_iso()),
        );
        self.guardar_ocultos(l)
    }

    /// Vuelve a mostrar un elemento quitado. Devuelve su entrada (None si no estaba)
    pub fn restaurar(&self, ruta: &str) -> std::io::Result<Option<Mapa>> {
        let ruta = abspath(ruta);
        let mut l = self.ocultos();
        let Some(i) = l.iter().position(|m| m.texto("ruta") == Some(ruta.as_str())) else { return Ok(None) };
        let e = l.remove(i);
        self.guardar_ocultos(l)?;
        Ok(Some(e))
    }

    /// `volver_a_mostrar`: importar de nuevo algo quitado lo vuelve a poner (comparando la ruta tal cual)
    fn volver_a_mostrar(&self, ruta: &str) {
        let Some(Valor::Mapa(mut datos)) = leer_json(&self.archivo_ocultos()) else { return };
        let Some(antes) = datos.lista("ocultos").map(<[Valor]>::to_vec) else { return };
        let despues: Vec<Valor> = antes.iter().filter(|o| !matches!(o, Valor::Mapa(m) if m.texto("ruta") == Some(ruta))).cloned().collect();
        if despues.len() != antes.len() {
            datos.poner("ocultos", Valor::Lista(despues));
            let _ = escribir_json(&self.archivo_ocultos(), &Valor::Mapa(datos));
        }
    }

    /// `BookService.import_file`: copia un archivo o una carpeta a su categoría (la pedida o la de su tipo)
    pub fn importar(&self, origen: &str, categoria: Option<&str>) -> Mapa {
        let abs = abspath(&prig_plataforma::py::expanduser(origen));
        if std::fs::metadata(&abs).is_err() {
            return Mapa::new().con("error", format!("El archivo u origen no existe: {origen}"));
        }
        let nombre = basename(&abs);
        let pedida = categoria.map(str::to_lowercase);
        let cat = match pedida.as_deref().and_then(|c| CATEGORIAS.iter().find(|x| **x == c)) {
            Some(c) => *c,
            None => categoria_de(&abs),
        };
        let destino = join(&join(&self.raiz, cat), &nombre);
        let r: Result<(), String> = (|| {
            if abspath(&abs) != abspath(&destino) {
                if Path::new(&abs).is_dir() {
                    copiar_arbol(Path::new(&abs), Path::new(&destino))?;
                } else {
                    std::fs::copy(&abs, &destino).map_err(|e| prig_plataforma::py::error_os(&e, &destino))?;
                    if let Ok(m) = std::fs::metadata(&abs).and_then(|m| m.modified()) {
                        let _ = std::fs::File::options().write(true).open(&destino).and_then(|f| f.set_modified(m));
                    }
                }
            }
            Ok(())
        })();
        if let Err(e) = r {
            return Mapa::new().con("error", format!("Error importando elemento: {e}"));
        }
        self.volver_a_mostrar(&abspath(&destino));
        let tam = std::fs::metadata(&destino).ok().filter(|m| m.is_file()).map(|m| redondear(m.len() as f64 / (1024.0 * 1024.0), 2)).unwrap_or(0.0);
        let ext = splitext(&nombre).1.to_lowercase().replace('.', "");
        Mapa::new()
            .con("id", nombre.as_str())
            .con("uid", relpath(&destino, &self.raiz))
            .con("category", cat.to_uppercase())
            .con("category_id", cat)
            .con("title", titulo_de_nombre(&nombre))
            .con("filename", nombre.as_str())
            .con("path", destino)
            .con("ext", ext)
            .con("size_mb", Valor::Real(tam))
            .con("analyzed", false)
    }

    /// La categoría por la carpeta en que está (o, en la raíz, por su tipo)
    fn categoria_de_ruta(&self, ruta: &str) -> &'static str {
        let rel = relpath(ruta, &self.raiz);
        match rel.split('/').next() {
            Some(c) if rel.contains('/') => CATEGORIAS.iter().find(|x| **x == c).copied().unwrap_or_else(|| categoria_de(ruta)),
            _ => categoria_de(ruta),
        }
    }

    // ------------------------------------------------------------------------------------------ elementos

    /// `_resolve_item`: un id (nombre, ruta relativa o absoluta) a un elemento de la biblioteca o a un proyecto guardado
    pub fn resolver(&self, id: &str, proyectos: &[String]) -> Option<Elemento> {
        if id.is_empty() {
            return None;
        }
        let mut candidatos = Vec::new();
        if isabs(id) {
            candidatos.push(id.to_string());
        }
        candidatos.push(join(&self.raiz, id));
        candidatos.extend(CATEGORIAS.iter().map(|c| join(&join(&self.raiz, c), id)));
        for c in candidatos {
            let a = abspath(&c);
            if dentro(&a, &self.raiz) && Path::new(&a).exists() {
                return Some(Elemento { ruta: a, proyecto: false });
            }
        }
        proyectos
            .iter()
            .find(|p| Path::new(p.as_str()).is_dir() && (p.as_str() == id || basename(p) == id))
            .map(|p| Elemento { ruta: p.clone(), proyecto: true })
    }

    /// `_metadata_key`: la ruta relativa a la biblioteca con «/» cambiado por «__»
    fn clave_ficha(&self, ruta: &str) -> String {
        relpath(ruta, &self.raiz).replace('/', "__")
    }

    fn archivos_ficha(&self, ruta: &str) -> Vec<PathBuf> {
        let dir = self.en("metadata");
        let mut v = vec![dir.join(format!("{}.json", self.clave_ficha(ruta)))];
        let antigua = dir.join(format!("{}.json", basename(ruta)));
        if !v.contains(&antigua) {
            v.push(antigua);
        }
        v
    }

    /// `get_metadata`: la ficha de IA (la de clave por ruta y, si no, la antigua por nombre)
    pub fn ficha(&self, ruta: &str) -> Option<Valor> {
        self.archivos_ficha(ruta).iter().find_map(|f| if f.exists() { leer_json(f) } else { None })
    }

    /// `BookService.list_books(categoria)`, sin lo que el usuario quitó. Err si una ficha no es un objeto (Python
    /// falla con AttributeError en ese caso)
    pub fn listar(&self, filtro: Option<&str>, proyectos: &[Valor]) -> Result<Vec<Mapa>, String> {
        let ocultos = self.rutas_ocultas();
        let filtro = filtro.map(|f| f.to_lowercase());
        let mut dirs: Vec<(String, Option<&str>)> = Vec::new();
        match filtro.as_deref().and_then(|f| CATEGORIAS.iter().find(|c| **c == f)) {
            Some(c) => dirs.push((join(&self.raiz, c), Some(c))),
            None => {
                dirs.push((self.raiz.clone(), None));
                dirs.extend(CATEGORIAS.iter().map(|c| (join(&self.raiz, c), Some(*c))));
            }
        }
        let mut vistos: HashSet<String> = HashSet::new();
        let mut items = Vec::new();
        for (dir, cat) in &dirs {
            let Ok(lectura) = std::fs::read_dir(dir) else { continue };
            let mut nombres: Vec<String> = lectura.flatten().map(|e| e.file_name().to_string_lossy().into_owned()).collect();
            nombres.sort();
            for nombre in nombres {
                let ruta = join(dir, &nombre);
                if nombre == "metadata" || nombre.starts_with('.') || vistos.contains(&ruta) || (*dir == self.raiz && INFRAESTRUCTURA.contains(&nombre.as_str())) {
                    continue;
                }
                if *dir == self.raiz && CATEGORIAS.contains(&nombre.as_str()) {
                    continue;
                }
                let p = Path::new(&ruta);
                let es_dir = p.is_dir();
                let ext = if es_dir { "dir".to_string() } else { ext_de(&nombre) };
                if !es_dir && !VISIBLES.contains(&ext.as_str()) {
                    continue;
                }
                vistos.insert(ruta.clone());
                let tam = if es_dir {
                    0.0
                } else {
                    match std::fs::metadata(p) {
                        Ok(m) => redondear(m.len() as f64 / (1024.0 * 1024.0), 2),
                        Err(_) => continue,
                    }
                };
                if Self::oculto(&ruta, &ocultos) {
                    continue;
                }
                let categoria = cat.unwrap_or_else(|| categoria_de(&ruta));
                let meta = self.ficha(&ruta);
                let m = match &meta {
                    None => None,
                    Some(Valor::Mapa(m)) => Some(m),
                    Some(_) => return Err(format!("la ficha de {nombre} no es un objeto")),
                };
                let titulo = m.and_then(|m| m.get("title")).filter(|t| t.verdad()).cloned().unwrap_or_else(|| Valor::Texto(titulo_de_nombre(&nombre)));
                let fallida = m.is_some_and(|m| m.verdad("analysis_failed"));
                items.push(
                    Mapa::new()
                        .con("id", nombre.clone())
                        .con("uid", relpath(&ruta, &self.raiz))
                        .con("category", categoria.to_uppercase())
                        .con("category_id", categoria)
                        .con("title", titulo)
                        .con("filename", nombre.clone())
                        .con("path", ruta.clone())
                        .con("ext", ext.clone())
                        .con("size_mb", Valor::Real(tam))
                        .con("indexable", !es_dir && INDEXABLES.contains(&ext.as_str()))
                        .con("analyzed", m.is_some_and(|m| !m.is_empty()) && !fallida)
                        .con("analysis_failed", fallida)
                        .con("metadata", meta.clone().unwrap_or(Valor::Nulo)),
                );
            }
        }
        if filtro.is_none() || matches!(filtro.as_deref(), Some("projects") | Some("all")) {
            for sp in proyectos {
                let ruta = match sp {
                    Valor::Mapa(m) => match m.get("path") {
                        Some(Valor::Texto(t)) => t.clone(),
                        _ => continue,
                    },
                    otro => otro.texto_py(),
                };
                if ruta.is_empty() || vistos.contains(&ruta) || !Path::new(&ruta).is_dir() || Self::oculto(&abspath(&ruta), &ocultos) {
                    continue;
                }
                vistos.insert(ruta.clone());
                let nombre = match sp {
                    Valor::Mapa(m) => m.get("name").filter(|n| n.verdad()).cloned(),
                    _ => None,
                }
                .unwrap_or_else(|| {
                    let b = basename(&ruta);
                    Valor::Texto(if b.is_empty() { ruta.clone() } else { b })
                });
                let meta = self.ficha(&ruta).filter(|m| m.verdad()).unwrap_or_else(|| {
                    Valor::Mapa(Mapa::new().con("title", nombre.clone()).con("path", ruta.clone()).con("is_project", true))
                });
                items.push(
                    Mapa::new()
                        .con("id", basename(&ruta))
                        .con("uid", ruta.clone())
                        .con("category", "PROJECTS")
                        .con("category_id", "projects")
                        .con("title", nombre)
                        .con("filename", basename(&ruta))
                        .con("path", ruta.clone())
                        .con("ext", "project")
                        .con("is_project", true)
                        .con("size_mb", Valor::Real(0.0))
                        .con("indexable", false)
                        .con("analyzed", true)
                        .con("analysis_failed", false)
                        .con("metadata", meta),
                );
            }
        }
        Ok(items)
    }

    // ------------------------------------------------------------------------------------------ catálogos

    fn abrir(&self, nombre: &str, escribir: bool) -> Option<Connection> {
        let ruta = self.indice().join(nombre);
        if !ruta.exists() {
            return None;
        }
        let flags = if escribir { OpenFlags::SQLITE_OPEN_READ_WRITE } else { OpenFlags::SQLITE_OPEN_READ_ONLY };
        let c = Connection::open_with_flags(ruta, flags | OpenFlags::SQLITE_OPEN_NO_MUTEX).ok()?;
        let _ = c.busy_timeout(std::time::Duration::from_secs(10));
        Some(c)
    }

    /// `get_indexed_paths`: las rutas que ya están en el catálogo de búsqueda (None si no se puede leer)
    pub fn rutas_indexadas(&self) -> Option<HashSet<String>> {
        let Some(c) = self.abrir("catalog.db", false) else { return Some(HashSet::new()) };
        let mut st = c.prepare("SELECT relative_path, metadata_json FROM books").ok()?;
        let filas = st.query_map([], |f| Ok((f.get::<_, Option<String>>(0)?, f.get::<_, Option<String>>(1)?))).ok()?;
        let mut v = HashSet::new();
        for f in filas.flatten() {
            v.insert(self.ruta_catalogo(f.0.as_deref(), f.1.as_deref()));
        }
        Some(v)
    }

    fn ruta_catalogo(&self, rel: Option<&str>, meta: Option<&str>) -> String {
        let abs = meta.and_then(|m| prig_plataforma::json::leer(m).ok()).and_then(|m| match m {
            Valor::Mapa(m) => m.texto("abs_path").filter(|a| !a.is_empty()).map(String::from),
            _ => None,
        });
        abspath(&abs.unwrap_or_else(|| join(&self.raiz, rel.unwrap_or_default())))
    }

    /// Los libros del catálogo de búsqueda que son `ruta` o están dentro: (source_id, ruta, sha256, fragmentos)
    fn en_catalogo(&self, ruta: &str) -> Vec<(String, String, String, i64)> {
        let Some(c) = self.abrir("catalog.db", false) else { return Vec::new() };
        let Ok(mut st) = c.prepare(
            "SELECT b.source_id, b.relative_path, b.metadata_json, b.sha256, (SELECT COUNT(*) FROM chunks k WHERE k.source_id = b.source_id) FROM books b",
        ) else {
            return Vec::new();
        };
        let Ok(filas) = st.query_map([], |f| {
            Ok((f.get::<_, String>(0)?, f.get::<_, Option<String>>(1)?, f.get::<_, Option<String>>(2)?, f.get::<_, Option<String>>(3)?, f.get::<_, i64>(4)?))
        }) else {
            return Vec::new();
        };
        filas
            .flatten()
            .filter_map(|(id, rel, meta, sha, n)| {
                let r = self.ruta_catalogo(rel.as_deref(), meta.as_deref());
                dentro(&r, ruta).then(|| (id, r, sha.unwrap_or_default().to_lowercase(), n))
            })
            .collect()
    }

    /// Los libros de la base de conocimiento que vienen de estos (por id o por huella): (source_id, afirmaciones, ficha)
    fn en_conocimiento(&self, ids: &[String], huellas: &[String]) -> Vec<(String, i64, bool)> {
        let Some(c) = self.abrir("knowledge.db", false) else { return Vec::new() };
        let Ok(mut st) = c.prepare(
            "SELECT b.source_id, lower(coalesce(b.sha256, '')), (SELECT COUNT(*) FROM claims x WHERE x.source_id = b.source_id), \
             EXISTS(SELECT 1 FROM book_profiles p WHERE p.source_id = b.source_id) FROM books b",
        ) else {
            return Vec::new();
        };
        let Ok(filas) = st.query_map([], |f| Ok((f.get::<_, String>(0)?, f.get::<_, String>(1)?, f.get::<_, i64>(2)?, f.get::<_, bool>(3)?))) else {
            return Vec::new();
        };
        filas.flatten().filter(|(id, sha, _, _)| ids.contains(id) || (!sha.is_empty() && huellas.contains(sha))).map(|(id, _, n, p)| (id, n, p)).collect()
    }

    // ------------------------------------------------------------------------------------------ inventario

    /// El nombre con que se guardan las citas y las páginas corregidas (`_book_stem`)
    fn tallo(ruta: &str) -> String {
        splitext(&basename(ruta)).0
    }

    /// Cómo puede haber llamado la interfaz a un elemento al guardar un recorte (`book_id`)
    fn nombres(&self, ruta: &str) -> Vec<String> {
        vec![basename(ruta), relpath(ruta, &self.raiz), ruta.to_string()]
    }

    fn ediciones(&self, ruta: &str) -> Vec<PathBuf> {
        let tallo = Self::tallo(ruta);
        let dir = self.en("citas").join("ediciones");
        let Ok(l) = std::fs::read_dir(&dir) else { return Vec::new() };
        let mut v: Vec<PathBuf> = l
            .flatten()
            .filter(|e| {
                let n = e.file_name().to_string_lossy().into_owned();
                n.strip_prefix(&format!("{tallo}_p")).and_then(|r| r.strip_suffix(".txt")).is_some_and(|d| !d.is_empty() && d.chars().all(|c| c.is_ascii_digit()))
            })
            .map(|e| e.path())
            .collect();
        v.sort();
        v
    }

    fn recortes_de(&self, ruta: &str) -> Vec<String> {
        let nombres = self.nombres(ruta);
        match leer_json(&self.archivo_recortes()) {
            Some(Valor::Mapa(m)) => m
                .iter()
                .filter(|(_, v)| matches!(v, Valor::Mapa(x) if x.texto("book_id").is_some_and(|b| nombres.iter().any(|n| n == b))))
                .map(|(k, _)| k.clone())
                .collect(),
            _ => Vec::new(),
        }
    }

    fn citas_de(&self, ruta: &str) -> (Option<PathBuf>, usize) {
        let f = self.en("citas").join(format!("{}.json", Self::tallo(ruta)));
        if !f.exists() {
            return (None, 0);
        }
        let n = match leer_json(&f) {
            Some(Valor::Mapa(m)) => m.lista("citas").map(|l| l.len()).unwrap_or(0),
            _ => 0,
        };
        (Some(f), n)
    }

    /// Los archivos que una carpeta muestra (recursivo, sin ocultos ni infraestructura), con su ruta relativa
    fn contenido(ruta: &str) -> Vec<String> {
        let mut v = Vec::new();
        let mut pila = vec![PathBuf::from(ruta)];
        while let Some(d) = pila.pop() {
            let Ok(l) = std::fs::read_dir(&d) else { continue };
            for e in l.flatten() {
                let n = e.file_name().to_string_lossy().into_owned();
                if n.starts_with('.') || n == "node_modules" || n == "__pycache__" {
                    continue;
                }
                let p = e.path();
                if e.file_type().is_ok_and(|t| t.is_dir()) {
                    pila.push(p);
                } else if VISIBLES.contains(&ext_de(&n).as_str()) {
                    v.push(p.to_string_lossy().into_owned());
                }
            }
            if v.len() > 5000 {
                break;
            }
        }
        v.sort();
        v
    }

    /// Lo que Prig guarda de un archivo (o de una carpeta en sí): {pieza: {cuenta, detalle}}
    fn piezas_de(&self, ruta: &str, catalogo: &[(String, String, String, i64)]) -> Mapa {
        let mut m = Mapa::new();
        let fichas = self.archivos_ficha(ruta).into_iter().filter(|f| f.exists()).count();
        m.poner("ficha", fichas as i128);
        if !Path::new(ruta).is_dir() {
            m.poner("citas", self.citas_de(ruta).1 as i128);
            m.poner("ediciones", self.ediciones(ruta).len() as i128);
            m.poner("recortes", self.recortes_de(ruta).len() as i128);
        }
        let propios: Vec<&(String, String, String, i64)> = catalogo.iter().filter(|c| c.1 == ruta).collect();
        m.poner("indice", propios.iter().map(|c| c.3).sum::<i64>() as i128);
        let ids: Vec<String> = propios.iter().map(|c| c.0.clone()).collect();
        let huellas: Vec<String> = propios.iter().map(|c| c.2.clone()).collect();
        let k = self.en_conocimiento(&ids, &huellas);
        m.poner("conocimiento", k.iter().map(|x| x.1 + x.2 as i64).sum::<i64>() as i128);
        m
    }

    /// El inventario de un elemento para decidir qué quitar: sus piezas (con totales de lo que contiene, si es una
    /// carpeta) y, en una carpeta, sus archivos uno a uno
    pub fn inventario(&self, e: &Elemento) -> Mapa {
        let catalogo = self.en_catalogo(&e.ruta);
        let es_dir = Path::new(&e.ruta).is_dir();
        let propias = self.piezas_de(&e.ruta, &catalogo);
        let mut totales = propias.clone();
        let mut archivos = Vec::new();
        if es_dir {
            let ocultos = self.rutas_ocultas();
            for f in Self::contenido(&e.ruta) {
                let p = self.piezas_de(&f, &catalogo);
                for (k, v) in p.iter() {
                    let n = totales.get(k).and_then(Valor::entero).unwrap_or(0) + v.entero().unwrap_or(0);
                    totales.poner(k.clone(), n);
                }
                let tam = std::fs::metadata(&f).map(|m| m.len()).unwrap_or(0);
                archivos.push(Valor::Mapa(
                    Mapa::new()
                        .con("ruta", f.clone())
                        .con("rel", relpath(&f, &e.ruta))
                        .con("bytes", tam as i128)
                        .con("oculto", Self::oculto(&f, &ocultos))
                        .con("piezas", p),
                ));
            }
        }
        let piezas: Vec<Valor> = PIEZAS
            .iter()
            .filter(|(k, _, _)| totales.contiene(k))
            .map(|(k, nombre, que)| {
                Valor::Mapa(Mapa::new().con("id", *k).con("nombre", *nombre).con("descripcion", *que).con("cuenta", totales.valor(k).clone()))
            })
            .collect();
        Mapa::new()
            .con("ruta", e.ruta.clone())
            .con("titulo", self.titulo(e))
            .con("es_carpeta", es_dir)
            .con("proyecto", e.proyecto)
            .con("dentro_de_la_biblioteca", dentro(&e.ruta, &self.raiz))
            .con("piezas", Valor::Lista(piezas))
            .con("archivos", Valor::Lista(archivos))
    }

    fn titulo(&self, e: &Elemento) -> String {
        match self.ficha(&e.ruta) {
            Some(Valor::Mapa(m)) if m.texto("title").is_some_and(|t| !t.is_empty()) => m.texto("title").unwrap_or_default().to_string(),
            _ => titulo_de_nombre(&basename(&e.ruta)),
        }
    }

    // ------------------------------------------------------------------------------------------ quitar

    /// Quita de la vista `e` entero (o, si es una carpeta y se dan `archivos`, solo esos) y borra de lo que Prig
    /// guarda las `piezas` elegidas. Nunca borra los archivos del usuario. Devuelve el resumen de lo hecho
    pub fn quitar(&self, e: &Elemento, piezas: &BTreeSet<String>, archivos: Option<&[String]>) -> Result<Mapa, String> {
        let mut objetivos: Vec<String> = Vec::new();
        let mut ocultados: Vec<String> = Vec::new();
        match archivos {
            Some(sel) if Path::new(&e.ruta).is_dir() => {
                for a in sel {
                    let r = abspath(&join(&e.ruta, a));
                    if !dentro(&r, &e.ruta) || r == e.ruta || !Path::new(&r).exists() {
                        return Err(format!("«{a}» no está dentro de «{}»", basename(&e.ruta)));
                    }
                    let hijo = Elemento { ruta: r.clone(), proyecto: false };
                    self.ocultar(&hijo, &titulo_de_nombre(&basename(&r))).map_err(|x| x.to_string())?;
                    ocultados.push(r.clone());
                    objetivos.push(r);
                }
            }
            _ => {
                self.ocultar(e, &self.titulo(e)).map_err(|x| x.to_string())?;
                ocultados.push(e.ruta.clone());
                objetivos.push(e.ruta.clone());
            }
        }

        // lo que cuelga de cada objetivo: él mismo y, si es una carpeta, lo que contiene
        let mut rutas: Vec<String> = Vec::new();
        for o in &objetivos {
            rutas.push(o.clone());
            if Path::new(o).is_dir() {
                rutas.extend(Self::contenido(o));
            }
        }
        let quiere = |p: &str| piezas.contains(p);
        let mut hecho = Mapa::new();
        let mut cuenta = |k: &str, n: usize| {
            let v = hecho.get(k).and_then(Valor::entero).unwrap_or(0) + n as i128;
            hecho.poner(k, v);
        };

        if quiere("ficha") {
            for r in &rutas {
                let n = self.archivos_ficha(r).iter().filter(|f| f.exists() && std::fs::remove_file(f).is_ok()).count();
                cuenta("ficha", n);
            }
        }
        if quiere("citas") {
            for r in &rutas {
                if let (Some(f), n) = self.citas_de(r) {
                    if std::fs::remove_file(&f).is_ok() {
                        cuenta("citas", n);
                    }
                }
            }
        }
        if quiere("ediciones") {
            for r in &rutas {
                let n = self.ediciones(r).iter().filter(|f| std::fs::remove_file(f).is_ok()).count();
                cuenta("ediciones", n);
            }
        }
        if quiere("recortes") {
            let ids: HashSet<String> = rutas.iter().flat_map(|r| self.recortes_de(r)).collect();
            if !ids.is_empty() {
                if let Some(Valor::Mapa(mut m)) = leer_json(&self.archivo_recortes()) {
                    for i in &ids {
                        m.quitar(i);
                    }
                    escribir_json(&self.archivo_recortes(), &Valor::Mapa(m)).map_err(|x| x.to_string())?;
                    cuenta("recortes", ids.len());
                }
            }
        }

        let catalogo: Vec<(String, String, String, i64)> = objetivos.iter().flat_map(|o| self.en_catalogo(o)).collect();
        if quiere("conocimiento") {
            let ids: Vec<String> = catalogo.iter().map(|c| c.0.clone()).collect();
            let mut huellas: Vec<String> = catalogo.iter().map(|c| c.2.clone()).collect();
            // lo que no llegó al catálogo de búsqueda se reconoce por su huella
            for r in &rutas {
                if !Path::new(r).is_dir() && INDEXABLES.contains(&ext_de(r).as_str()) && !catalogo.iter().any(|c| c.1 == *r) {
                    if let Some(h) = sha256_de(r) {
                        huellas.push(h);
                    }
                }
            }
            let libros: Vec<String> = self.en_conocimiento(&ids, &huellas).into_iter().map(|x| x.0).collect();
            if !libros.is_empty() {
                let n = self.borrar_conocimiento(&libros).map_err(|x| format!("base de conocimiento: {x}"))?;
                cuenta("conocimiento", n);
            }
        }
        if quiere("indice") && !catalogo.is_empty() {
            let n = self.borrar_del_catalogo(&catalogo.iter().map(|c| c.0.clone()).collect::<Vec<_>>()).map_err(|x| format!("índice: {x}"))?;
            cuenta("indice", n);
        }
        if !ocultados.is_empty() || hecho.verdad("indice") || hecho.verdad("conocimiento") {
            self.avisar_cambio();
        }
        Ok(Mapa::new()
            .con("success", true)
            .con("ruta", e.ruta.clone())
            .con("ocultados", Valor::Lista(ocultados.into_iter().map(Valor::Texto).collect()))
            .con("borrado", hecho)
            .con("archivos_borrados", 0))
    }

    /// Fragmentos, secciones y capítulos de estos libros en el catálogo de búsqueda (`DBCatalog.delete_book`)
    fn borrar_del_catalogo(&self, ids: &[String]) -> rusqlite::Result<usize> {
        let Some(mut c) = self.abrir("catalog.db", true) else { return Ok(0) };
        let t = c.transaction()?;
        let mut n = 0;
        for id in ids {
            n += t.query_row("SELECT COUNT(*) FROM chunks WHERE source_id = ?1", params![id], |f| f.get::<_, i64>(0))? as usize;
            for tabla in ["chunks", "sections", "chapters", "books"] {
                t.execute(&format!("DELETE FROM {tabla} WHERE source_id = ?1"), params![id])?;
            }
        }
        t.commit()?;
        Ok(n)
    }

    /// Todo lo de estos libros en la base de conocimiento (`PackImporter._borrar_libro`, su fila y su ficha) y los
    /// conceptos que tocaban, recalculados como en `unificar` (los que se quedan sin afirmaciones se van). Los
    /// dosieres de esos conceptos citaban el libro: se descartan y quedan por reconstruir
    fn borrar_conocimiento(&self, libros: &[String]) -> rusqlite::Result<usize> {
        let Some(mut c) = self.abrir("knowledge.db", true) else { return Ok(0) };
        let t = c.transaction()?;
        let mut afectados: BTreeSet<String> = BTreeSet::new();
        let mut n = 0usize;
        for id in libros {
            {
                let mut st = t.prepare("SELECT claim_id, coalesce(concept_id, '') FROM claims WHERE source_id = ?1")?;
                let filas: Vec<(String, String)> = st.query_map(params![id], |f| Ok((f.get(0)?, f.get(1)?)))?.flatten().collect();
                n += filas.len();
                for (claim, concepto) in filas {
                    t.execute("DELETE FROM claims_fts WHERE claim_id = ?1", params![claim])?;
                    afectados.insert(concepto);
                }
                let mut st = t.prepare("SELECT DISTINCT concept_id FROM aliases WHERE source_id = ?1")?;
                afectados.extend(st.query_map(params![id], |f| f.get::<_, String>(0))?.flatten());
            }
            for tabla in ["claims", "relations", "symbols", "aliases", "sections", "figures", "questions", "book_profiles", "books"] {
                t.execute(&format!("DELETE FROM {tabla} WHERE source_id = ?1"), params![id])?;
            }
        }
        afectados.remove("");
        for cid in &afectados {
            let (menciones, libros_n): (i64, i64) =
                t.query_row("SELECT COUNT(*), COUNT(DISTINCT source_id) FROM claims WHERE concept_id = ?1", params![cid], |f| Ok((f.get(0)?, f.get(1)?)))?;
            if menciones == 0 {
                let alias: i64 = t.query_row("SELECT COUNT(*) FROM aliases WHERE concept_id = ?1", params![cid], |f| f.get(0))?;
                if alias == 0 {
                    t.execute("DELETE FROM concepts WHERE concept_id = ?1", params![cid])?;
                    t.execute("DELETE FROM vectores WHERE concept_id = ?1", params![cid]).ok();
                }
            } else {
                let dominios: Vec<String> = {
                    let mut st = t.prepare("SELECT DISTINCT domain FROM claims WHERE concept_id = ?1 AND domain IS NOT NULL AND domain != '' ORDER BY domain")?;
                    let v = st.query_map(params![cid], |f| f.get::<_, String>(0))?.flatten().collect();
                    v
                };
                let json = prig_plataforma::json::escribir_compacto(&Valor::Lista(dominios.iter().cloned().map(Valor::Texto).collect()));
                t.execute(
                    "UPDATE concepts SET mentions = ?2, books = ?3, is_bridge = ?4, domains = ?5 WHERE concept_id = ?1",
                    params![cid, menciones, libros_n, (dominios.len() >= 2) as i64, json],
                )?;
            }
            t.execute("DELETE FROM dossiers WHERE concept_id = ?1", params![cid])?;
        }
        t.execute("INSERT OR REPLACE INTO meta VALUES ('unificacion_pendiente', ?1)", params![prig_plataforma::py::ahora_iso()])?;
        t.commit()?;
        Ok(n)
    }

    /// Para el backend de Python mientras conviven: el índice que tiene en memoria ya no vale (se rehace al cambiar
    /// la fecha de `.index/generacion`)
    fn avisar_cambio(&self) {
        let _ = std::fs::create_dir_all(self.indice());
        let _ = std::fs::write(self.indice().join("generacion"), prig_plataforma::py::ahora_iso());
    }
}

/// `hashlib.sha256` de un archivo, en hexadecimal
fn sha256_de(ruta: &str) -> Option<String> {
    use sha2::{Digest, Sha256};
    use std::io::Read;
    let mut f = std::fs::File::open(ruta).ok()?;
    let mut h = Sha256::new();
    let mut b = vec![0u8; 1 << 16];
    loop {
        let n = f.read(&mut b).ok()?;
        if n == 0 {
            break;
        }
        h.update(&b[..n]);
    }
    Some(h.finalize().iter().map(|x| format!("{x:02x}")).collect())
}

#[cfg(test)]
mod pruebas {
    use super::*;

    fn escribir(ruta: &str, t: &str) {
        std::fs::create_dir_all(Path::new(ruta).parent().unwrap()).unwrap();
        std::fs::write(ruta, t).unwrap();
    }

    /// Una biblioteca con un libro indexado (y en la base de conocimiento, compartiendo un concepto con otro libro),
    /// una carpeta con dos archivos, citas, recortes y páginas corregidas
    fn biblioteca() -> (String, Estante) {
        let raiz = std::env::temp_dir().join(format!("prig_estante_{}", id_prueba()));
        let r = raiz.to_string_lossy().into_owned();
        let e = Estante::new(&r);
        escribir(&format!("{r}/books/libro.pdf"), "%PDF falso");
        escribir(&format!("{r}/books/otro.pdf"), "%PDF otro");
        escribir(&format!("{r}/projects/repo/a.py"), "print(1)");
        escribir(&format!("{r}/projects/repo/sub/b.md"), "# b");
        escribir(&format!("{r}/metadata/books__libro.pdf.json"), r#"{"title": "Mi libro"}"#);
        escribir(&format!("{r}/metadata/projects__repo__a.py.json"), r#"{"title": "A"}"#);
        escribir(&format!("{r}/citas/libro.json"), r#"{"stem": "libro", "citas": [{"id": "c1"}, {"id": "c2"}]}"#);
        escribir(&format!("{r}/citas/ediciones/libro_p3.txt"), "corregida");
        escribir(&format!("{r}/citas/ediciones/libro_px.txt"), "no es una página");
        escribir(&format!("{r}/snippets.json"), r#"{"s1": {"book_id": "libro.pdf"}, "s2": {"book_id": "otro.pdf"}}"#);
        std::fs::create_dir_all(format!("{r}/.index")).unwrap();
        let c = Connection::open(format!("{r}/.index/catalog.db")).unwrap();
        c.execute_batch(&format!(
            "CREATE TABLE books (source_id TEXT, relative_path TEXT, metadata_json TEXT, sha256 TEXT);
             CREATE TABLE chunks (source_id TEXT); CREATE TABLE sections (source_id TEXT); CREATE TABLE chapters (source_id TEXT);
             INSERT INTO books VALUES ('s_libro', 'BOOKS/libro.pdf', '{{\"abs_path\": \"{r}/books/libro.pdf\"}}', 'AA');
             INSERT INTO books VALUES ('s_otro', 'BOOKS/otro.pdf', '{{\"abs_path\": \"{r}/books/otro.pdf\"}}', 'BB');
             INSERT INTO chunks VALUES ('s_libro'), ('s_libro'), ('s_otro'); INSERT INTO sections VALUES ('s_libro');"
        ))
        .unwrap();
        let k = Connection::open(format!("{r}/.index/knowledge.db")).unwrap();
        k.execute_batch(
            "CREATE TABLE books (source_id TEXT, sha256 TEXT);
             CREATE TABLE claims (claim_id TEXT, concept_id TEXT, source_id TEXT, domain TEXT);
             CREATE TABLE claims_fts (claim_id TEXT);
             CREATE TABLE concepts (concept_id TEXT, mentions INT, books INT, is_bridge INT, domains TEXT);
             CREATE TABLE aliases (concept_id TEXT, source_id TEXT);
             CREATE TABLE relations (source_id TEXT); CREATE TABLE symbols (source_id TEXT); CREATE TABLE sections (source_id TEXT);
             CREATE TABLE figures (source_id TEXT); CREATE TABLE questions (source_id TEXT); CREATE TABLE book_profiles (source_id TEXT);
             CREATE TABLE dossiers (concept_id TEXT); CREATE TABLE vectores (concept_id TEXT);
             CREATE TABLE meta (clave TEXT PRIMARY KEY, valor TEXT);
             INSERT INTO books VALUES ('k_libro', 'aa'), ('k_otro', 'bb');
             INSERT INTO claims VALUES ('x1', 'c:solo', 'k_libro', 'ml'), ('x2', 'c:comun', 'k_libro', 'ml'), ('x3', 'c:comun', 'k_otro', 'stats');
             INSERT INTO claims_fts VALUES ('x1'), ('x2'), ('x3');
             INSERT INTO concepts VALUES ('c:solo', 1, 1, 0, '[\"ml\"]'), ('c:comun', 2, 2, 1, '[\"ml\", \"stats\"]');
             INSERT INTO book_profiles VALUES ('k_libro');
             INSERT INTO dossiers VALUES ('c:comun'), ('c:solo'); INSERT INTO vectores VALUES ('c:solo');",
        )
        .unwrap();
        (r, e)
    }

    fn id_prueba() -> String {
        use std::sync::atomic::{AtomicUsize, Ordering};
        static N: AtomicUsize = AtomicUsize::new(0);
        format!("{}_{}", std::process::id(), N.fetch_add(1, Ordering::SeqCst))
    }

    fn todas() -> BTreeSet<String> {
        PIEZAS.iter().map(|p| p.0.to_string()).collect()
    }

    fn cuenta(c: &Connection, sql: &str) -> i64 {
        c.query_row(sql, [], |f| f.get(0)).unwrap()
    }

    #[test]
    fn inventario_de_un_libro() {
        let (r, e) = biblioteca();
        let el = e.resolver("libro.pdf", &[]).unwrap();
        let inv = e.inventario(&el);
        let piezas: Vec<(String, i128)> = inv
            .lista("piezas")
            .unwrap()
            .iter()
            .map(|p| if let Valor::Mapa(m) = p { (m.texto("id").unwrap().to_string(), m.valor("cuenta").entero().unwrap()) } else { panic!() })
            .collect();
        let esperado: Vec<(String, i128)> =
            [("ficha", 1), ("citas", 2), ("ediciones", 1), ("recortes", 1), ("indice", 2), ("conocimiento", 3)].iter().map(|(k, n)| (k.to_string(), *n)).collect();
        assert_eq!(piezas, esperado);
        std::fs::remove_dir_all(r).ok();
    }

    #[test]
    fn quitar_un_libro_no_borra_el_archivo_y_limpia_lo_elegido() {
        let (r, e) = biblioteca();
        let el = e.resolver("books/libro.pdf", &[]).unwrap();
        let res = e.quitar(&el, &todas(), None).unwrap();
        assert!(Path::new(&format!("{r}/books/libro.pdf")).exists(), "el archivo del usuario sigue");
        assert!(!Path::new(&format!("{r}/metadata/books__libro.pdf.json")).exists());
        assert!(!Path::new(&format!("{r}/citas/libro.json")).exists());
        assert!(!Path::new(&format!("{r}/citas/ediciones/libro_p3.txt")).exists());
        assert!(Path::new(&format!("{r}/citas/ediciones/libro_px.txt")).exists(), "no es una página de este libro");
        let rec = std::fs::read_to_string(format!("{r}/snippets.json")).unwrap();
        assert!(!rec.contains("\"s1\"") && rec.contains("\"s2\""));
        // fuera de la lista, el otro sigue
        let l = e.listar(None, &[]).unwrap();
        let rutas: Vec<&str> = l.iter().map(|m| m.texto("path").unwrap()).collect();
        assert!(!rutas.contains(&format!("{r}/books/libro.pdf").as_str()));
        assert!(rutas.contains(&format!("{r}/books/otro.pdf").as_str()));
        // catálogo: solo lo del otro
        let c = Connection::open(format!("{r}/.index/catalog.db")).unwrap();
        assert_eq!(cuenta(&c, "SELECT COUNT(*) FROM chunks"), 1);
        assert_eq!(cuenta(&c, "SELECT COUNT(*) FROM books"), 1);
        // conocimiento: el concepto propio se va; el compartido queda con el otro libro y deja de ser puente
        let k = Connection::open(format!("{r}/.index/knowledge.db")).unwrap();
        assert_eq!(cuenta(&k, "SELECT COUNT(*) FROM concepts WHERE concept_id = 'c:solo'"), 0);
        assert_eq!(cuenta(&k, "SELECT COUNT(*) FROM vectores"), 0);
        assert_eq!(cuenta(&k, "SELECT mentions * 100 + books * 10 + is_bridge FROM concepts WHERE concept_id = 'c:comun'"), 110);
        let dom: String = k.query_row("SELECT domains FROM concepts WHERE concept_id = 'c:comun'", [], |f| f.get(0)).unwrap();
        assert_eq!(dom, r#"["stats"]"#);
        assert_eq!(cuenta(&k, "SELECT COUNT(*) FROM dossiers"), 0);
        assert_eq!(cuenta(&k, "SELECT COUNT(*) FROM claims_fts"), 1);
        assert_eq!(cuenta(&k, "SELECT COUNT(*) FROM book_profiles"), 0);
        assert_eq!(res.mapa("borrado").unwrap().valor("indice").entero(), Some(2));
        // y se puede volver a poner
        assert!(e.restaurar(&format!("{r}/books/libro.pdf")).unwrap().is_some());
        assert!(e.listar(None, &[]).unwrap().iter().any(|m| m.texto("path") == Some(&format!("{r}/books/libro.pdf"))));
        std::fs::remove_dir_all(r).ok();
    }

    #[test]
    fn quitar_solo_parte_de_una_carpeta_y_guardar_lo_elegido() {
        let (r, e) = biblioteca();
        let el = e.resolver("projects/repo", &[]).unwrap();
        let inv = e.inventario(&el);
        assert_eq!(inv.lista("archivos").unwrap().len(), 2);
        // solo «a.py», y sin borrar su ficha
        let piezas: BTreeSet<String> = ["indice".to_string()].into_iter().collect();
        e.quitar(&el, &piezas, Some(&["a.py".to_string()])).unwrap();
        assert!(Path::new(&format!("{r}/metadata/projects__repo__a.py.json")).exists());
        assert!(Path::new(&format!("{r}/projects/repo/a.py")).exists());
        assert!(Estante::oculto(&format!("{r}/projects/repo/a.py"), &e.rutas_ocultas()));
        assert!(!Estante::oculto(&format!("{r}/projects/repo"), &e.rutas_ocultas()), "la carpeta se sigue viendo");
        // nada fuera de la carpeta
        assert!(e.quitar(&el, &piezas, Some(&["../../books/otro.pdf".to_string()])).is_err());
        std::fs::remove_dir_all(r).ok();
    }
}

/// `shutil.copytree(origen, destino, dirs_exist_ok=True)` (con los enlaces seguidos, como hace por defecto)
fn copiar_arbol(origen: &Path, destino: &Path) -> Result<(), String> {
    std::fs::create_dir_all(destino).map_err(|e| prig_plataforma::py::error_os(&e, &destino.to_string_lossy()))?;
    let l = std::fs::read_dir(origen).map_err(|e| prig_plataforma::py::error_os(&e, &origen.to_string_lossy()))?;
    for e in l.flatten() {
        let (de, a) = (e.path(), destino.join(e.file_name()));
        if de.is_dir() {
            copiar_arbol(&de, &a)?;
        } else {
            std::fs::copy(&de, &a).map_err(|e| prig_plataforma::py::error_os(&e, &a.to_string_lossy()))?;
        }
    }
    Ok(())
}
