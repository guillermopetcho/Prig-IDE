use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::Arc;
use std::time::Instant;
use thiserror::Error;
use tokio::io::{AsyncRead, AsyncReadExt};
use tokio::process::Command;
use tokio::sync::Mutex;

/// Lo que se guarda de stdout y de stderr (el resto se lee y se descarta: si no, un programa que escribe sin parar
/// llenaba la memoria de Prig hasta el tiempo límite)
const MAX_SALIDA: usize = 2 * 1024 * 1024;

/// El intérprete de Python: el del entorno de Prig si se indica (`PRIG_PYTHON`, p. ej. el de su .venv), si no `python3`
fn python() -> String {
    std::env::var("PRIG_PYTHON").ok().filter(|p| !p.trim().is_empty()).unwrap_or_else(|| "python3".to_string())
}

/// Lee una tubería entera guardando como mucho MAX_SALIDA bytes
async fn leer_con_tope<R: AsyncRead + Unpin>(mut r: R) -> Vec<u8> {
    let mut guardado = Vec::new();
    let mut tramo = [0u8; 8192];
    let mut recortado = false;
    loop {
        match r.read(&mut tramo).await {
            Ok(0) | Err(_) => break,
            Ok(n) => {
                let cabe = MAX_SALIDA.saturating_sub(guardado.len()).min(n);
                guardado.extend_from_slice(&tramo[..cabe]);
                recortado |= cabe < n;
            }
        }
    }
    if recortado {
        guardado.extend_from_slice(b"\n[... salida recortada por Prig ...]\n");
    }
    guardado
}
use tracing::{debug, warn};

#[derive(Error, Debug)]
pub enum RunnerError {
    #[error("Archivo no encontrado: {0}")]
    FileNotFound(String),
    #[error("Error de compilación ({0}): {1}")]
    CompilationFailed(String, String),
    #[error("Compilador no disponible: {0}")]
    CompilerNotFound(String),
    #[error("Tiempo límite excedido ({0}s)")]
    Timeout(u64),
    #[error("Error de E/S ejecutando proceso: {0}")]
    Io(#[from] std::io::Error),
    #[error("Error parseando notebook: {0}")]
    NotebookParse(String),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RunResult {
    pub success: bool,
    #[serde(default)]
    pub cancelled: bool,
    pub stdout: String,
    pub stderr: String,
    pub exit_code: i32,
    pub elapsed: f64,
}

#[derive(Clone, Default)]
pub struct CodeRunner {
    pub active_processes: Arc<Mutex<HashMap<String, u32>>>,
    /// Ejecuciones canceladas a pedido (para responder `cancelled: true`)
    cancelados: Arc<Mutex<HashSet<String>>>,
}

impl CodeRunner {
    pub fn new() -> Self {
        Self {
            active_processes: Arc::new(Mutex::new(HashMap::new())),
            cancelados: Arc::new(Mutex::new(HashSet::new())),
        }
    }

    pub async fn cancel(&self, run_id: &str) -> bool {
        let mut map = self.active_processes.lock().await;
        if let Some(pid) = map.remove(run_id) {
            debug!("Cancelando proceso con PID {}", pid);
            self.cancelados.lock().await.insert(run_id.to_string());
            // El proceso es líder de su grupo (process_group(0)): se mata también a sus hijos
            matar_grupo(pid);
            true
        } else {
            false
        }
    }

    pub async fn run_file(
        &self,
        file_path: &str,
        cwd: Option<&str>,
        timeout_secs: u64,
        run_id: Option<String>,
    ) -> Result<RunResult, RunnerError> {
        let path = Path::new(file_path);
        if !path.exists() {
            return Err(RunnerError::FileNotFound(file_path.to_string()));
        }

        let abs_path = path.canonicalize().unwrap_or_else(|_| path.to_path_buf());
        let working_dir = match cwd {
            Some(c) if Path::new(c).is_dir() => PathBuf::from(c),
            _ => abs_path.parent().unwrap_or(Path::new(".")).to_path_buf(),
        };

        let ext = abs_path
            .extension()
            .and_then(|e| e.to_str())
            .unwrap_or("")
            .to_lowercase();

        let mut temp_to_clean: Option<PathBuf> = None;
        let mut cmd;

        if ext == "ipynb" {
            let content = tokio::fs::read_to_string(&abs_path).await?;
            let py_code = extract_python_from_notebook(&content)
                .map_err(|e| RunnerError::NotebookParse(e.to_string()))?;

            let nanos = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos();
            let temp_py = std::env::temp_dir().join(format!("prig_nb_{}.py", nanos));
            tokio::fs::write(&temp_py, py_code).await?;
            temp_to_clean = Some(temp_py.clone());

            cmd = Command::new(python());
            cmd.arg(&temp_py);
        } else if ext == "py" {
            cmd = Command::new(python());
            cmd.arg(&abs_path);
        } else if ext == "js" {
            cmd = Command::new("node");
            cmd.arg(&abs_path);
        } else if ext == "sh" || ext == "bash" {
            cmd = Command::new("bash");
            cmd.arg(&abs_path);
        } else if ext == "rs" {
            let nanos = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos();
            let temp_bin = std::env::temp_dir().join(format!("prig_rs_bin_{}", nanos));

            let compile_res = Command::new("rustc")
                .arg("-O")
                .arg(&abs_path)
                .arg("-o")
                .arg(&temp_bin)
                .current_dir(&working_dir)
                .output()
                .await?;

            if !compile_res.status.success() {
                let stderr = String::from_utf8_lossy(&compile_res.stderr).to_string();
                return Err(RunnerError::CompilationFailed("rustc".to_string(), stderr));
            }

            temp_to_clean = Some(temp_bin.clone());
            cmd = Command::new(&temp_bin);
        } else if ext == "c" || ext == "cpp" || ext == "cc" {
            let compiler = if ext == "c" { "gcc" } else { "g++" };
            let nanos = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos();
            let temp_bin = std::env::temp_dir().join(format!("prig_cpp_bin_{}", nanos));

            let std_flag = if ext == "c" { "-std=c11" } else { "-std=c++20" };
            let compile_res = Command::new(compiler)
                .arg(std_flag)
                .arg("-O2")
                .arg(&abs_path)
                .arg("-o")
                .arg(&temp_bin)
                .arg("-lm")
                .current_dir(&working_dir)
                .output()
                .await?;

            if !compile_res.status.success() {
                let stderr = String::from_utf8_lossy(&compile_res.stderr).to_string();
                return Err(RunnerError::CompilationFailed(compiler.to_string(), stderr));
            }

            temp_to_clean = Some(temp_bin.clone());
            cmd = Command::new(&temp_bin);
        } else {
            // Intento por defecto: Python
            cmd = Command::new(python());
            cmd.arg(&abs_path);
        }

        cmd.current_dir(&working_dir)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .process_group(0)
            .kill_on_drop(true);

        let start = Instant::now();
        let mut child = cmd.spawn()?;

        let pid = child.id();
        if let (Some(ref r_id), Some(p)) = (&run_id, pid) {
            let mut map = self.active_processes.lock().await;
            map.insert(r_id.clone(), p);
        }

        let salida_tarea = tokio::spawn(leer_con_tope(child.stdout.take().expect("stdout")));
        let error_tarea = tokio::spawn(leer_con_tope(child.stderr.take().expect("stderr")));
        let timeout_duration = std::time::Duration::from_secs(timeout_secs);
        let wait_res = match tokio::time::timeout(timeout_duration, child.wait()).await {
            Ok(Ok(status)) => {
                let stdout = salida_tarea.await.unwrap_or_default();
                let stderr = error_tarea.await.unwrap_or_default();
                Ok(Ok(std::process::Output { status, stdout, stderr }))
            }
            Ok(Err(e)) => Ok(Err(e)),
            Err(e) => {
                // Tiempo agotado: se mata el grupo entero (los hijos del programa también)
                if let Some(p) = pid {
                    matar_grupo(p);
                }
                let _ = child.wait().await;
                Err(e)
            }
        };

        if let Some(ref r_id) = run_id {
            let mut map = self.active_processes.lock().await;
            map.remove(r_id);
        }
        let cancelado = match run_id {
            Some(ref r_id) => self.cancelados.lock().await.remove(r_id),
            None => false,
        };

        if let Some(temp_file) = temp_to_clean {
            let _ = tokio::fs::remove_file(temp_file).await;
        }

        match wait_res {
            Ok(Ok(output)) => {
                let elapsed = (start.elapsed().as_secs_f64() * 1000.0).round() / 1000.0;
                let exit_code = output.status.code().unwrap_or(if output.status.success() { 0 } else { 1 });
                let stdout = String::from_utf8_lossy(&output.stdout).to_string();
                let stderr = String::from_utf8_lossy(&output.stderr).to_string();

                Ok(RunResult {
                    success: output.status.success() && !cancelado,
                    cancelled: cancelado,
                    stdout,
                    stderr,
                    exit_code,
                    elapsed,
                })
            }
            Ok(Err(e)) => Err(RunnerError::Io(e)),
            Err(_) => {
                warn!("Proceso excedió el tiempo límite de {}s", timeout_secs);
                Err(RunnerError::Timeout(timeout_secs))
            }
        }
    }
}

fn matar_grupo(pid: u32) {
    unsafe {
        let _ = libc::kill(-(pid as i32), libc::SIGKILL);
        let _ = libc::kill(pid as i32, libc::SIGKILL);
    }
}

fn extract_python_from_notebook(json_str: &str) -> Result<String, serde_json::Error> {
    let val: serde_json::Value = serde_json::from_str(json_str)?;
    let mut code_lines = Vec::new();

    if let Some(cells) = val.get("cells").and_then(|c| c.as_array()) {
        for cell in cells {
            if cell.get("cell_type").and_then(|t| t.as_str()) == Some("code") {
                if let Some(src) = cell.get("source") {
                    let s = match src {
                        serde_json::Value::Array(arr) => arr
                            .iter()
                            .filter_map(|line| line.as_str())
                            .collect::<Vec<_>>()
                            .join(""),
                        serde_json::Value::String(line) => line.clone(),
                        _ => String::new(),
                    };
                    code_lines.push(s);
                    code_lines.push("\n\n".to_string());
                }
            }
        }
    }

    Ok(code_lines.join(""))
}

