use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::fs;
use std::path::{Component, Path, PathBuf};
use thiserror::Error;

/// `os.path.abspath` de Python: la ruta absoluta con `.` y `..` resueltos sobre el texto, sin mirar el disco ni
/// seguir enlaces. Así se comparan las rutas en Python (`FileManager.resolve` + `commonpath`). Antes, una ruta con
/// un componente que no existía quedaba sin normalizar: `zz/../../x` pasaba el control (`starts_with` compara
/// componentes) y `write_file` creaba `zz` y escribía FUERA del espacio de trabajo.
pub fn normalizar(ruta: &Path) -> PathBuf {
    let absoluta = if ruta.is_absolute() {
        ruta.to_path_buf()
    } else {
        std::env::current_dir().unwrap_or_else(|_| PathBuf::from("/")).join(ruta)
    };
    let mut salida = PathBuf::new();
    for c in absoluta.components() {
        match c {
            Component::Prefix(p) => salida.push(p.as_os_str()),
            Component::RootDir => salida.push(Component::RootDir.as_os_str()),
            Component::CurDir => {}
            Component::ParentDir => {
                salida.pop();
            }
            Component::Normal(n) => salida.push(n),
        }
    }
    if salida.as_os_str().is_empty() {
        salida.push("/");
    }
    salida
}

#[derive(Error, Debug)]
pub enum FsError {
    #[error("Ruta no especificada")]
    EmptyPath,
    #[error("Acceso denegado: '{0}' está fuera de la carpeta de trabajo.")]
    AccessDenied(String),
    #[error("Archivo no encontrado: {0}")]
    NotFound(String),
    #[error("El directorio no existe: {0}")]
    DirectoryNotFound(String),
    #[error("No se puede eliminar la carpeta raíz del espacio de trabajo.")]
    CannotDeleteRoot,
    #[error("Error de E/S: {0}")]
    Io(#[from] std::io::Error),
    #[error("Error parseando notebook: {0}")]
    NotebookParse(String),
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct FileNode {
    pub name: String,
    pub path: String,
    pub is_dir: bool,
    /// `null` en los archivos, como en Python (`"children": None`)
    pub children: Option<Vec<FileNode>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NotebookCell {
    pub id: String,
    pub index: usize,
    #[serde(rename = "type")]
    pub cell_type: String,
    pub source: String,
    pub execution_count: Option<i64>,
    pub outputs: Vec<serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NotebookData {
    pub path: String,
    pub name: String,
    pub cells: Vec<NotebookCell>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileContentResponse {
    pub path: String,
    pub name: String,
    pub content: String,
    pub is_notebook: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub notebook_data: Option<NotebookData>,
}

#[derive(Debug, Clone)]
pub struct FileManager {
    pub base_dir: PathBuf,
    pub extra_allowed_roots: Vec<PathBuf>,
    /// La segunda carpeta del explorador (para copiar código de una a otra): también se puede leer y editar
    pub segunda_dir: Option<PathBuf>,
}

impl FileManager {
    pub fn new(base_dir: PathBuf) -> Self {
        let mut extra = Vec::new();
        if let Ok(home) = std::env::var("HOME") {
            extra.push(PathBuf::from(&home).join(".prig_books"));
            // ruta_base() de hub/servicio.py: PRIG_HUB_DIR o ~/.prig_hub
            let hub = std::env::var("PRIG_HUB_DIR").ok().filter(|h| !h.is_empty()).map(PathBuf::from);
            extra.push(hub.unwrap_or_else(|| PathBuf::from(&home).join(".prig_hub")).join("propios"));
        }

        Self {
            base_dir: normalizar(&base_dir),
            extra_allowed_roots: extra.iter().map(|r| normalizar(r)).collect(),
            segunda_dir: None,
        }
    }

    pub fn set_base_dir(&mut self, path: &Path) -> Result<PathBuf, FsError> {
        let abs = if path.is_absolute() {
            path.to_path_buf()
        } else {
            self.base_dir.join(path)
        };

        let abs = normalizar(&abs);
        if !abs.is_dir() {
            return Err(FsError::DirectoryNotFound(abs.to_string_lossy().to_string()));
        }
        self.base_dir = abs.clone();
        Ok(abs)
    }

    /// Fija (o quita, con `None`) la segunda carpeta; una que no es un directorio se ignora
    pub fn set_segunda_dir(&mut self, path: Option<&Path>) {
        self.segunda_dir = path.map(normalizar).filter(|p| p.is_dir());
    }

    pub fn allowed_roots(&self) -> Vec<PathBuf> {
        let mut roots = vec![self.base_dir.clone()];
        for extra in &self.extra_allowed_roots {
            roots.push(extra.clone());
        }
        if let Some(segunda) = &self.segunda_dir {
            roots.push(segunda.clone());
        }
        roots
    }

    pub fn is_path_allowed(&self, abs_path: &Path) -> bool {
        let abs_path = normalizar(abs_path);
        for root in self.allowed_roots() {
            if abs_path.starts_with(&root) {
                return true;
            }
        }
        false
    }

    pub fn resolve(&self, path: &str) -> Result<PathBuf, FsError> {
        if path.is_empty() {
            return Err(FsError::EmptyPath);
        }

        let p = Path::new(path);
        let abs = if p.is_absolute() {
            p.to_path_buf()
        } else {
            self.base_dir.join(p)
        };

        let canonical = normalizar(&abs);

        if !self.is_path_allowed(&canonical) {
            return Err(FsError::AccessDenied(canonical.to_string_lossy().to_string()));
        }

        Ok(canonical)
    }

    pub fn get_file_tree(&self, path: Option<&str>, max_depth: usize) -> Vec<FileNode> {
        let target_dir = match path {
            Some(p) if !p.is_empty() => match self.resolve(p) {
                Ok(resolved) => resolved,
                Err(_) => return Vec::new(),
            },
            _ => self.base_dir.clone(),
        };

        if !target_dir.is_dir() || !self.is_path_allowed(&target_dir) {
            return Vec::new();
        }

        self.build_tree_recursive(&target_dir, max_depth, 0)
    }

    fn build_tree_recursive(&self, dir: &Path, max_depth: usize, current_depth: usize) -> Vec<FileNode> {
        if current_depth >= max_depth {
            return Vec::new();
        }

        let read_dir = match fs::read_dir(dir) {
            Ok(rd) => rd,
            Err(_) => return Vec::new(),
        };

        let ignored: HashSet<&str> = [
            "__pycache__", "node_modules", "venv", ".venv", "env", ".env",
            ".git", ".github", ".ipynb_checkpoints", "dist", "build",
            ".cache", "site-packages", ".idea", ".vscode", ".gemini", "target",
        ].iter().cloned().collect();

        let mut entries = Vec::new();
        for entry in read_dir.flatten() {
            let fname_os = entry.file_name();
            let name = fname_os.to_string_lossy().to_string();

            // Filtrar ocultos excepto .gitignore y .env.example
            if (name.starts_with('.') && name != ".gitignore" && name != ".env.example") || ignored.contains(name.as_str()) {
                continue;
            }

            let path = entry.path();
            let is_dir = path.is_dir();
            entries.push((name, path, is_dir));
        }

        // Ordenar: primero carpetas, luego alfabético insensibles a mayúsculas
        entries.sort_by(|(name_a, _, is_dir_a), (name_b, _, is_dir_b)| {
            match (is_dir_a, is_dir_b) {
                (true, false) => std::cmp::Ordering::Less,
                (false, true) => std::cmp::Ordering::Greater,
                _ => name_a.to_lowercase().cmp(&name_b.to_lowercase()),
            }
        });

        let mut nodes = Vec::with_capacity(entries.len());
        for (name, path, is_dir) in entries {
            let path_str = path.to_string_lossy().to_string();
            let children = if is_dir {
                Some(self.build_tree_recursive(&path, max_depth, current_depth + 1))
            } else {
                None
            };

            nodes.push(FileNode {
                name,
                path: path_str,
                is_dir,
                children,
            });
        }

        nodes
    }

    pub fn read_file(&self, file_path: &str) -> Result<FileContentResponse, FsError> {
        let abs_path = self.resolve(file_path)?;
        if !abs_path.is_file() {
            return Err(FsError::NotFound(file_path.to_string()));
        }

        let raw_content = fs::read_to_string(&abs_path)
            .or_else(|_| {
                // Fallback para archivos con bytes no UTF-8 válidos
                fs::read(&abs_path).map(|b| String::from_utf8_lossy(&b).to_string())
            })?;

        let fname = abs_path
            .file_name()
            .map(|f| f.to_string_lossy().to_string())
            .unwrap_or_default();

        let ext = abs_path
            .extension()
            .and_then(|e| e.to_str())
            .unwrap_or("")
            .to_lowercase();

        if ext == "ipynb" {
            let notebook_data = self.read_notebook_structured(&raw_content, &abs_path.to_string_lossy());
            Ok(FileContentResponse {
                path: abs_path.to_string_lossy().to_string(),
                name: fname,
                content: raw_content,
                is_notebook: true,
                notebook_data: Some(notebook_data),
            })
        } else {
            Ok(FileContentResponse {
                path: abs_path.to_string_lossy().to_string(),
                name: fname,
                content: raw_content,
                is_notebook: false,
                notebook_data: None,
            })
        }
    }

    pub fn read_notebook_structured(&self, json_str: &str, file_path: &str) -> NotebookData {
        let fname = Path::new(file_path)
            .file_name()
            .map(|f| f.to_string_lossy().to_string())
            .unwrap_or_default();

        let val: serde_json::Value = match serde_json::from_str(json_str) {
            Ok(v) => v,
            Err(_) => {
                return NotebookData {
                    path: file_path.to_string(),
                    name: fname,
                    cells: Vec::new(),
                }
            }
        };

        let raw_cells = val.get("cells").and_then(|c| c.as_array());
        let mut cells = Vec::new();

        if let Some(cell_list) = raw_cells {
            for (idx, cell) in cell_list.iter().enumerate() {
                let cell_type = cell
                    .get("cell_type")
                    .and_then(|t| t.as_str())
                    .unwrap_or("code")
                    .to_string();

                let mut source_str = match cell.get("source") {
                    Some(serde_json::Value::Array(arr)) => arr
                        .iter()
                        .filter_map(|s| s.as_str())
                        .collect::<Vec<_>>()
                        .join(""),
                    Some(serde_json::Value::String(s)) => s.clone(),
                    _ => String::new(),
                };

                // Procesar attachments de markdown
                if let Some(attachments) = cell.get("attachments").and_then(|a| a.as_object()) {
                    for (attach_name, mime_map) in attachments {
                        if let Some(m_obj) = mime_map.as_object() {
                            for (mime_type, b64_val) in m_obj {
                                let b64_str = match b64_val {
                                    serde_json::Value::Array(arr) => arr
                                        .iter()
                                        .filter_map(|s| s.as_str())
                                        .collect::<Vec<_>>()
                                        .join(""),
                                    serde_json::Value::String(s) => s.clone(),
                                    _ => String::new(),
                                };
                                let clean_b64 = b64_str.replace(['\n', '\r'], "").trim().to_string();
                                let data_uri = format!("data:{};base64,{}", mime_type, clean_b64);
                                source_str = source_str.replace(&format!("attachment:{}", attach_name), &data_uri);
                            }
                        }
                    }
                }

                let mut outputs = Vec::new();
                if let Some(raw_outs) = cell.get("outputs").and_then(|o| o.as_array()) {
                    for out in raw_outs {
                        let out_type = out.get("output_type").and_then(|t| t.as_str()).unwrap_or("");
                        if out_type == "stream" {
                            let text = match out.get("text") {
                                Some(serde_json::Value::Array(arr)) => arr
                                    .iter()
                                    .filter_map(|s| s.as_str())
                                    .collect::<Vec<_>>()
                                    .join(""),
                                Some(serde_json::Value::String(s)) => s.clone(),
                                _ => String::new(),
                            };
                            let name = out.get("name").and_then(|n| n.as_str()).unwrap_or("stdout");
                            outputs.push(serde_json::json!({
                                "type": "stream",
                                "text": text,
                                "name": name
                            }));
                        } else if out_type == "execute_result" || out_type == "display_data" {
                            if let Some(data_obj) = out.get("data").and_then(|d| d.as_object()) {
                                if let Some(html) = data_obj.get("text/html") {
                                    let html_str = match html {
                                        serde_json::Value::Array(arr) => arr
                                            .iter()
                                            .filter_map(|s| s.as_str())
                                            .collect::<Vec<_>>()
                                            .join(""),
                                        serde_json::Value::String(s) => s.clone(),
                                        _ => String::new(),
                                    };
                                    outputs.push(serde_json::json!({
                                        "type": "html",
                                        "text": html_str
                                    }));
                                } else {
                                    let mut img_found = false;
                                    for mime in &["image/png", "image/jpeg", "image/jpg", "image/svg+xml", "image/gif"] {
                                        if let Some(img_val) = data_obj.get(*mime) {
                                            let img_data = match img_val {
                                                serde_json::Value::Array(arr) => arr
                                                    .iter()
                                                    .filter_map(|s| s.as_str())
                                                    .collect::<Vec<_>>()
                                                    .join(""),
                                                serde_json::Value::String(s) => s.clone(),
                                                _ => String::new(),
                                            };
                                            outputs.push(serde_json::json!({
                                                "type": "image",
                                                "data": img_data,
                                                "mime": mime
                                            }));
                                            img_found = true;
                                            break;
                                        }
                                    }

                                    if !img_found {
                                        if let Some(plain) = data_obj.get("text/plain") {
                                            let plain_str = match plain {
                                                serde_json::Value::Array(arr) => arr
                                                    .iter()
                                                    .filter_map(|s| s.as_str())
                                                    .collect::<Vec<_>>()
                                                    .join(""),
                                                serde_json::Value::String(s) => s.clone(),
                                                _ => String::new(),
                                            };
                                            outputs.push(serde_json::json!({
                                                "type": "text",
                                                "text": plain_str
                                            }));
                                        }
                                    }
                                }
                            }
                        } else if out_type == "error" {
                            let ename = out.get("ename").and_then(|e| e.as_str()).unwrap_or("");
                            let evalue = out.get("evalue").and_then(|e| e.as_str()).unwrap_or("");
                            let tb = match out.get("traceback") {
                                Some(serde_json::Value::Array(arr)) => arr
                                    .iter()
                                    .filter_map(|s| s.as_str())
                                    .collect::<Vec<_>>()
                                    .join("\n"),
                                Some(serde_json::Value::String(s)) => s.clone(),
                                _ => String::new(),
                            };
                            outputs.push(serde_json::json!({
                                "type": "error",
                                "text": format!("{}: {}\n{}", ename, evalue, tb)
                            }));
                        }
                    }
                }

                let exec_count = cell.get("execution_count").and_then(|c| c.as_i64());

                cells.push(NotebookCell {
                    id: format!("cell_{}", idx + 1),
                    index: idx + 1,
                    cell_type,
                    source: source_str,
                    execution_count: exec_count,
                    outputs,
                });
            }
        }

        NotebookData {
            path: file_path.to_string(),
            name: fname,
            cells,
        }
    }

    pub fn write_file(&self, file_path: &str, content: &str) -> Result<PathBuf, FsError> {
        let abs_path = self.resolve(file_path)?;
        if let Some(parent) = abs_path.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::write(&abs_path, content)?;
        Ok(abs_path)
    }

    pub fn create_item(&self, target_path: &str, is_dir: bool) -> Result<PathBuf, FsError> {
        let abs_path = self.resolve(target_path)?;
        if is_dir {
            fs::create_dir_all(&abs_path)?;
        } else {
            if let Some(parent) = abs_path.parent() {
                fs::create_dir_all(parent)?;
            }
            if !abs_path.exists() {
                fs::write(&abs_path, "")?;
            }
        }
        Ok(abs_path)
    }

    pub fn delete_item(&self, target_path: &str) -> Result<PathBuf, FsError> {
        let abs_path = self.resolve(target_path)?;

        // Prohibir borrar la raíz del workspace
        if abs_path == self.base_dir {
            return Err(FsError::CannotDeleteRoot);
        }
        for root in self.extra_allowed_roots.iter().chain(self.segunda_dir.iter()) {
            if &abs_path == root {
                return Err(FsError::CannotDeleteRoot);
            }
        }

        if abs_path.is_dir() {
            fs::remove_dir_all(&abs_path)?;
        } else if abs_path.is_file() {
            fs::remove_file(&abs_path)?;
        } else {
            return Err(FsError::NotFound(target_path.to_string()));
        }

        Ok(abs_path)
    }
}
