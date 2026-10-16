//! `prig`: la ventana de Prig IDE y el dueño de todos sus procesos (F9 de docs/plan-prig-rust.md), en lugar de
//! main.py con pywebview y Qt. La interfaz (HTML/JS, sin cambios) se abre en WebKitGTK con tao + wry; el servidor de
//! Rust corre en este mismo proceso y el backend de Python es un hijo que se arranca, se vigila y se cierra desde
//! aquí. Lo que `_blindar_qt` resolvía en Qt, aquí: micrófono y portapapeles permitidos, descargas con «Guardar
//! como…», enlaces externos y ventanas nuevas en el navegador del sistema sin bloquear la ventana.
//!
//! Sin pantalla (o si la ventana no se puede crear), la interfaz se abre en el navegador y Prig sigue en marcha
//! hasta Ctrl+C.

mod navegador;
mod servidores;

use servidores::{Puerto, Servidores};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use tao::event::{Event, StartCause, WindowEvent};
use tao::event_loop::{ControlFlow, EventLoopBuilder, EventLoopProxy};
use tao::window::WindowBuilder;
use wry::{NewWindowResponse, PermissionKind, PermissionResponse, WebViewBuilder};

const TITULO: &str = "Prig IDE - Editor & Tutor IA Local";

#[derive(Debug, Clone)]
enum Aviso {
    /// El backend está listo: se carga la interfaz
    Listo,
    /// El backend no arrancó: se enseña por qué
    Fallo(String),
    /// Ctrl+C o SIGTERM: se cierra todo
    Cerrar,
    /// La interfaz pide entrar o salir de la pantalla completa (`/api/ide/pantalla-completa`)
    PantallaCompleta,
}

fn pagina_espera() -> String {
    r#"<!doctype html><html><head><meta charset="utf-8"><style>
html,body{height:100%;margin:0;background:#1e1e2e;color:#cdd6f4;font:15px system-ui,sans-serif}
body{display:flex;align-items:center;justify-content:center;flex-direction:column;gap:14px}
.p{width:38px;height:38px;border:3px solid #45475a;border-top-color:#89b4fa;border-radius:50%;animation:g 1s linear infinite}
@keyframes g{to{transform:rotate(360deg)}}</style></head>
<body><div class="p"></div><div id="m">Arrancando Prig…</div></body></html>"#
        .into()
}

fn pagina_fallo(motivo: &str) -> String {
    let m = motivo.replace('&', "&amp;").replace('<', "&lt;");
    format!(
        r#"<!doctype html><html><head><meta charset="utf-8"><style>html,body{{margin:0;background:#1e1e2e;color:#cdd6f4;
font:15px system-ui,sans-serif}}body{{padding:40px}}code{{background:#313244;padding:2px 6px;border-radius:4px}}</style></head>
<body><h2>❌ Prig no pudo arrancar su servidor interno</h2><p>{m}</p>
<p>Para ver el fallo completo, arranca el backend suelto:<br>
<code>.venv/bin/python -c "import sys; sys.path.insert(0,'backend'); import app"</code></p></body></html>"#
    )
}

/// Señales: Ctrl+C y SIGTERM cierran todo en orden (como `shutdown_prig`)
fn escuchar_senales(proxy: Option<EventLoopProxy<Aviso>>, servidores: Option<Arc<Servidores>>) {
    let _ = std::thread::Builder::new().name("prig-senales".into()).spawn(move || {
        let Ok(rt) = tokio::runtime::Builder::new_current_thread().enable_all().build() else { return };
        rt.block_on(async {
            let mut term = match tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()) {
                Ok(t) => t,
                Err(_) => return,
            };
            tokio::select! {
                _ = tokio::signal::ctrl_c() => {}
                _ = term.recv() => {}
            }
        });
        match proxy {
            Some(p) if p.send_event(Aviso::Cerrar).is_ok() => {}
            _ => {
                if let Some(s) = servidores {
                    s.apagar();
                }
                std::process::exit(0);
            }
        }
    });
}

/// Hay pantalla gráfica donde abrir una ventana
fn hay_pantalla() -> bool {
    ["DISPLAY", "WAYLAND_DISPLAY", "BROADWAY_DISPLAY"].iter().any(|v| std::env::var_os(v).is_some_and(|x| !x.is_empty()))
}

/// Sin ventana: el navegador, y Prig sigue en marcha hasta Ctrl+C
fn modo_navegador(url: &str, servidores: Option<Arc<Servidores>>) -> ! {
    if let Some(s) = &servidores {
        if !s.esperar_python() {
            eprintln!("❌ El backend de Python no arrancó.");
            s.apagar();
            std::process::exit(1);
        }
    }
    println!("💡 Abriendo Prig IDE en el navegador...");
    navegador::abrir(url);
    println!("🌐 Prig IDE activo en: {url}\nPresiona Ctrl+C para salir.");
    escuchar_senales(None, servidores);
    loop {
        std::thread::park();
    }
}

/// Diagnóstico (PRIG_REGISTRO_JS=<url>): la página manda a esa dirección sus errores de JavaScript y su tamaño, para
/// ver qué pasa dentro de la ventana sin herramientas de desarrollo
fn registro_js(destino: &str) -> String {
    let destino = destino.replace(['\\', '"'], "");
    format!(
        r#"(function () {{
  const enviar = (tipo, datos) => {{ try {{ navigator.sendBeacon("{destino}", JSON.stringify({{tipo, datos, url: location.href}})); }} catch (e) {{}} }};
  window.addEventListener('error', e => enviar('error', String(e.message) + ' @ ' + (e.filename || '') + ':' + (e.lineno || '')));
  window.addEventListener('unhandledrejection', e => enviar('rechazo', String(e.reason && (e.reason.stack || e.reason))));
  const original = console.error;
  console.error = function (...a) {{ enviar('console.error', a.map(String).join(' ')); return original.apply(console, a); }};
  window.addEventListener('load', () => setTimeout(() => enviar('tamano', {{ancho: innerWidth, alto: innerHeight, dpr: devicePixelRatio,
    cuerpo: document.body && document.body.getBoundingClientRect().width}}), 3000));
}})();"#
    )
}

/// «Guardar como…» de GTK para una descarga (lo que hacía `descargar` en `_blindar_qt`)
fn elegir_destino(sugerido: &Path) -> Option<PathBuf> {
    use gtk::prelude::*;
    let casa = std::env::var_os("HOME").map(PathBuf::from).unwrap_or_else(|| PathBuf::from("/"));
    let carpeta = ["Descargas", "Downloads"].iter().map(|d| casa.join(d)).find(|d| d.is_dir()).unwrap_or(casa);
    let dialogo = gtk::FileChooserDialog::with_buttons(
        Some("Guardar como"),
        None::<&gtk::Window>,
        gtk::FileChooserAction::Save,
        &[("Cancelar", gtk::ResponseType::Cancel), ("Guardar", gtk::ResponseType::Accept)],
    );
    dialogo.set_do_overwrite_confirmation(true);
    dialogo.set_current_folder(&carpeta);
    if let Some(nombre) = sugerido.file_name() {
        dialogo.set_current_name(&nombre.to_string_lossy());
    }
    let respuesta = dialogo.run();
    let ruta = dialogo.filename();
    dialogo.close();
    if respuesta == gtk::ResponseType::Accept {
        ruta
    } else {
        None
    }
}

/// `prig --nota URL`: el bloc de notas en una ventana suelta (lo pide `/api/note/open-standalone`), sin servidores
/// propios: la página es la del Prig que ya está en marcha
fn ventana_nota(url: &str) -> ! {
    gtk::glib::set_prgname(Some("Prig-IDE"));
    let event_loop = tao::event_loop::EventLoop::new();
    let ventana = WindowBuilder::new()
        .with_title("Note - Bloc de Notas (Prig IDE)")
        .with_inner_size(tao::dpi::LogicalSize::new(840.0, 590.0))
        .with_min_inner_size(tao::dpi::LogicalSize::new(450.0, 400.0))
        .with_resizable(true)
        .build(&event_loop)
        .unwrap_or_else(|e| {
            eprintln!("⚠️ No se pudo crear la ventana de notas ({e}).");
            std::process::exit(1)
        });
    {
        use gtk::prelude::GtkWindowExt;
        use tao::platform::unix::WindowExtUnix;
        let icono = prig_server::resolve_project_root().join("assets/icon.svg");
        if icono.exists() {
            let _ = ventana.gtk_window().set_icon_from_file(&icono);
        }
    }
    let _vista = {
        use tao::platform::unix::WindowExtUnix;
        use wry::WebViewBuilderExtUnix;
        let caja = ventana.default_vbox().expect("la ventana de tao trae su caja");
        WebViewBuilder::new()
            .with_url(url)
            .with_clipboard(true)
            .with_new_window_req_handler(|u, _| {
                navegador::abrir(&u);
                NewWindowResponse::Deny
            })
            .build_gtk(caja)
            .unwrap_or_else(|e| {
                eprintln!("⚠️ No se pudo crear la vista web ({e}).");
                std::process::exit(1)
            })
    };
    event_loop.run(move |evento, _, control| {
        *control = ControlFlow::Wait;
        if let Event::WindowEvent { event: WindowEvent::CloseRequested, .. } = evento {
            *control = ControlFlow::Exit;
        }
    })
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if let Some(i) = args.iter().position(|a| a == "--nota") {
        ventana_nota(args.get(i + 1).map(String::as_str).unwrap_or("http://127.0.0.1:8000/static/note.html"));
    }
    let raiz = prig_server::resolve_project_root();
    let url_raiz = |puerto: u16| format!("http://{}:{puerto}", servidores::HOST);

    servidores::limpiar_huerfanos(&raiz);

    let (url, servidores) = match servidores::elegir_puerto() {
        Err(e) => {
            eprintln!("❌ {e}");
            std::process::exit(1);
        }
        Ok(Puerto::EnMarcha(p)) => (url_raiz(p), None),
        Ok(Puerto::Libre(listener)) => match Servidores::arrancar(&raiz, listener) {
            Ok(s) => {
                println!("⚡ Servidor nativo en Rust activo (puerto {}); esperando al backend de Python…", s.puerto);
                s.vigilar();
                (url_raiz(s.puerto), Some(s))
            }
            Err(e) => {
                eprintln!("❌ {e}");
                std::process::exit(1);
            }
        },
    };

    if !hay_pantalla() {
        modo_navegador(&url, servidores);
    }

    // El nombre de la aplicación da la clase de la ventana (WM_CLASS): con «Prig-IDE», el dock muestra el icono de
    // Prig (Prig-IDE.desktop tiene StartupWMClass=Prig-IDE) en vez de la tuerca gris
    gtk::glib::set_prgname(Some("Prig-IDE"));
    gtk::glib::set_application_name("Prig IDE");

    let event_loop = EventLoopBuilder::<Aviso>::with_user_event().build();
    // La interfaz es oscura, pero WebKitGTK dibuja la lista de un <select> con el tema de GTK del sistema (claro): con
    // el texto claro del CSS, las opciones salían blancas sobre blanco. Se pide la variante oscura del tema.
    {
        use gtk::glib::prelude::ObjectExt;
        if let Some(ajustes) = gtk::Settings::default() {
            ajustes.set_property("gtk-application-prefer-dark-theme", true);
        }
    }
    let proxy = event_loop.create_proxy();
    let ventana = match WindowBuilder::new()
        .with_title(TITULO)
        .with_inner_size(tao::dpi::LogicalSize::new(1280.0, 800.0))
        .with_min_inner_size(tao::dpi::LogicalSize::new(450.0, 400.0))
        .with_resizable(true)
        .build(&event_loop)
    {
        Ok(v) => v,
        Err(e) => {
            eprintln!("⚠️ No se pudo crear la ventana ({e}).");
            modo_navegador(&url, servidores);
        }
    };
    {
        use gtk::prelude::GtkWindowExt;
        use tao::platform::unix::WindowExtUnix;
        let icono = raiz.join("assets/icon.svg");
        if icono.exists() {
            let _ = ventana.gtk_window().set_icon_from_file(&icono);
        }
    }

    let webview = {
        use tao::platform::unix::WindowExtUnix;
        use wry::WebViewBuilderExtUnix;
        let caja = ventana.default_vbox().expect("la ventana de tao trae su caja");
        let mut builder = WebViewBuilder::new().with_html(pagina_espera());
        if let Ok(destino) = std::env::var("PRIG_REGISTRO_JS") {
            builder = builder.with_initialization_script(registro_js(&destino));
        }
        let builder = builder
            .with_clipboard(true)
            .with_devtools(std::env::var_os("PRIG_DEVTOOLS").is_some())
            // micrófono (el modo de voz y el audio reactivo) y portapapeles («Insertar en Editor»); lo demás, como
            // el navegador decida
            .with_permission_handler(|tipo| match tipo {
                PermissionKind::Microphone | PermissionKind::Camera | PermissionKind::Other => PermissionResponse::Allow,
                _ => PermissionResponse::Default,
            })
            // un enlace a fuera en la ventana principal se abre en el navegador
            .with_navigation_handler(|url| {
                if (url.starts_with("http://") || url.starts_with("https://")) && !navegador::es_local(&url) {
                    navegador::abrir(&url);
                    return false;
                }
                true
            })
            // window.open y target="_blank": siempre en el navegador, nunca otra ventana de Prig
            .with_new_window_req_handler(|url, _| {
                navegador::abrir(&url);
                NewWindowResponse::Deny
            })
            .with_download_started_handler(|_url, destino| match elegir_destino(destino) {
                Some(ruta) => {
                    *destino = ruta;
                    true
                }
                None => false,
            });
        match builder.build_gtk(caja) {
            Ok(w) => w,
            Err(e) => {
                eprintln!("⚠️ No se pudo crear la vista web ({e}).");
                modo_navegador(&url, servidores);
            }
        }
    };
    {
        // el micrófono necesita los flujos de medios de WebKitGTK, que vienen apagados
        use webkit2gtk::{SettingsExt, WebViewExt};
        use wry::WebViewExtUnix;
        if let Some(ajustes) = webview.webview().settings() {
            ajustes.set_enable_media_stream(true);
            ajustes.set_enable_mediasource(true);
            ajustes.set_javascript_can_access_clipboard(true);
        }
    }

    // Cuando Python responde, se carga la interfaz (antes, medio programa daba 502)
    match servidores.clone() {
        Some(s) => {
            let p = proxy.clone();
            std::thread::spawn(move || {
                let aviso = if s.esperar_python() { Aviso::Listo } else { Aviso::Fallo("El backend de Python no arrancó.".into()) };
                let _ = p.send_event(aviso);
            });
        }
        None => {
            let _ = proxy.send_event(Aviso::Listo);
        }
    }
    {
        let p = std::sync::Mutex::new(proxy.clone());
        prig_server::routes::escritorio::al_pedir_pantalla_completa(move || {
            let _ = p.lock().map(|p| p.send_event(Aviso::PantallaCompleta));
        });
    }
    escuchar_senales(Some(proxy), servidores.clone());

    let mut cerrando = false;
    event_loop.run(move |evento, _, control| {
        *control = ControlFlow::Wait;
        let cerrar = match evento {
            Event::NewEvents(StartCause::Init) => false,
            Event::UserEvent(Aviso::Listo) => {
                println!("✅ Servidor interno listo en {url}");
                let _ = webview.load_url(&url);
                false
            }
            Event::UserEvent(Aviso::Fallo(m)) => {
                eprintln!("❌ {m}");
                let _ = webview.load_html(&pagina_fallo(&m));
                false
            }
            Event::UserEvent(Aviso::Cerrar) => true,
            Event::UserEvent(Aviso::PantallaCompleta) => {
                let completa = ventana.fullscreen().is_some();
                ventana.set_fullscreen(if completa { None } else { Some(tao::window::Fullscreen::Borderless(None)) });
                false
            }
            Event::WindowEvent { event: WindowEvent::CloseRequested, .. } => true,
            _ => false,
        };
        if cerrar && !cerrando {
            cerrando = true;
            // la ventana desaparece ya; Python tiene hasta 20 s para soltar la GPU y parar lo que esté en curso
            ventana.set_visible(false);
            if let Some(s) = &servidores {
                s.apagar();
            }
            *control = ControlFlow::Exit;
        }
    });
}
