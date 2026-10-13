use prig_fs::FileManager;
use reqwest::Client;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime};
use tokio::sync::{Mutex, RwLock};

/// Cuánto esperan las peticiones a que el backend de Python responda cuando no está (arrancando o reiniciándose).
/// Pasado este plazo sin respuesta, las peticiones fallan enseguida con 502 hasta que vuelva.
pub const PLAZO_RESPALDO: Duration = Duration::from_secs(60);

/// Estado del backend de Python (el respaldo) visto desde el proxy.
#[derive(Default)]
pub struct EstadoRespaldo {
    /// Desde cuándo no responde (None: respondió la última vez).
    pub caido_desde: Option<Instant>,
}

#[derive(Clone)]
pub struct AppState {
    /// Raíz de Prig (la carpeta con frontend/ y assets/).
    pub base_dir: PathBuf,
    pub frontend_dir: PathBuf,
    pub assets_dir: Option<PathBuf>,
    pub fallback_url: String,
    /// Puerto de este servidor (para los orígenes de CORS).
    pub puerto: u16,
    pub start_time: Instant,
    pub http_client: Client,
    /// El espacio de trabajo. El dueño es el backend de Python: lo guarda en `config_path` (`last_workspace`) cada
    /// vez que cambia, y aquí se lee de ahí (`routes::workspace::espacio_de_trabajo`).
    pub file_mgr: Arc<RwLock<FileManager>>,
    pub config_path: PathBuf,
    /// Fecha de modificación de `config_path` la última vez que se leyó.
    pub config_visto: Arc<Mutex<Option<SystemTime>>>,
    pub respaldo: Arc<Mutex<EstadoRespaldo>>,
    pub plazo_respaldo: Duration,
}

impl AppState {
    pub fn new(base_dir: PathBuf, frontend_dir: PathBuf, assets_dir: Option<PathBuf>, fallback_url: String) -> Self {
        let config_path = crate::routes::workspace::get_config_path().unwrap_or_else(|| PathBuf::from(".prig_config.json"));
        Self::con_config(base_dir, frontend_dir, assets_dir, fallback_url, config_path)
    }

    /// Con un archivo de configuración concreto (los tests usan uno temporal).
    pub fn con_config(
        base_dir: PathBuf,
        frontend_dir: PathBuf,
        assets_dir: Option<PathBuf>,
        fallback_url: String,
        config_path: PathBuf,
    ) -> Self {
        // Sin tiempo límite total: el proxy transmite respuestas largas (el chat, las descargas de modelos)
        let http_client = Client::builder()
            .connect_timeout(Duration::from_secs(2))
            .pool_idle_timeout(Duration::from_secs(90))
            .pool_max_idle_per_host(20)
            .build()
            .unwrap_or_default();

        let initial_ws = crate::routes::workspace::load_last_workspace(&config_path, &base_dir);
        let file_mgr = Arc::new(RwLock::new(FileManager::new(initial_ws)));

        Self {
            base_dir,
            frontend_dir,
            assets_dir,
            fallback_url,
            puerto: 8000,
            start_time: Instant::now(),
            http_client,
            file_mgr,
            config_path,
            config_visto: Arc::new(Mutex::new(None)),
            respaldo: Arc::new(Mutex::new(EstadoRespaldo::default())),
            plazo_respaldo: PLAZO_RESPALDO,
        }
    }
}
