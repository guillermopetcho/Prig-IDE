use prig_server::{create_app, resolve_project_root, AppState};
use std::net::SocketAddr;
use tracing::info;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info,prig_server=debug")),
        )
        .init();

    info!("🚀 Inicializando Prig Native (Axum + Tokio)");

    let args: Vec<String> = std::env::args().collect();
    let port: u16 = std::env::var("PRIG_PORT")
        .ok()
        .and_then(|p| p.parse().ok())
        .unwrap_or_else(|| {
            let mut p = 8000;
            for i in 1..args.len() {
                if args[i] == "--port" && i + 1 < args.len() {
                    if let Ok(parsed) = args[i + 1].parse() {
                        p = parsed;
                    }
                }
            }
            p
        });

    let fallback_port: u16 = std::env::var("PRIG_PYTHON_PORT")
        .ok()
        .and_then(|p| p.parse().ok())
        .unwrap_or_else(|| {
            let mut p = 8001;
            for i in 1..args.len() {
                if args[i] == "--fallback-port" && i + 1 < args.len() {
                    if let Ok(parsed) = args[i + 1].parse() {
                        p = parsed;
                    }
                }
            }
            p
        });

    let project_root = resolve_project_root();
    let frontend_dir = project_root.join("frontend");
    let assets_dir = {
        let a = project_root.join("assets");
        if a.exists() {
            Some(a)
        } else {
            None
        }
    };

    let fallback_url = format!("http://127.0.0.1:{}", fallback_port);

    info!("📁 Raíz del proyecto: {}", project_root.display());
    info!("🎨 Frontend estático: {}", frontend_dir.display());
    info!("🔄 Proxy Dual-Stack hacia Python: {}", fallback_url);

    let n = prig_server::routes::moe::limpiar_huerfanos(&project_root);
    if n > 0 {
        info!("🧹 Motor MoE: cerrados {n} servidores que quedaron de una sesión anterior");
    }
    // Los recursos vivos (motor suave, modo frío): Python ya no los arranca si hay servidor de Rust
    prig_ia::vivo::recursos(&project_root).iniciar();
    let mut state = AppState::new(project_root.clone(), frontend_dir.clone(), assets_dir, fallback_url);
    state.puerto = port;

    // lo que Python preparaba al arrancar (las citas de muestra de las librerías)
    prig_server::routes::librerias::preparar();
    let app = create_app(state);

    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    info!("⚡ Prig Native Server escuchando en http://{}", addr);

    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await?;

    prig_ia::vivo::cerrar();
    info!("🛑 Prig Native Server detenido limpiamente.");
    Ok(())
}

async fn shutdown_signal() {
    let ctrl_c = async {
        tokio::signal::ctrl_c()
            .await
            .expect("Fallo al registrar manejador de Ctrl+C");
    };

    #[cfg(unix)]
    let terminate = async {
        tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
            .expect("Fallo al registrar manejador de SIGTERM")
            .recv()
            .await;
    };

    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        _ = ctrl_c => info!("Señal Ctrl+C recibida, iniciando apagado elegante..."),
        _ = terminate => info!("Señal SIGTERM recibida, iniciando apagado elegante..."),
    }
}
