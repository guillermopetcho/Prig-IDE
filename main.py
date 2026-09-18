import os
import sys
import time
import socket
import signal
import atexit
import threading
import traceback
import webbrowser
import urllib.error
import urllib.request

import uvicorn

HOST = "127.0.0.1"
PREFERRED_PORT = 8000
PORT_RANGE = 20  # puertos alternativos a probar si el preferido está ocupado

ROOT = os.path.dirname(os.path.abspath(__file__))

# El hilo del backend guarda aquí su excepción: si muere en silencio, la ventana
# nunca aparece y el usuario se queda sin ninguna pista de por qué.
_backend_error = {"exc": None}
_server: "Optional[uvicorn.Server]" = None
_backend_thread: "Optional[threading.Thread]" = None
_shutting_down = False
_shutdown_lock = threading.Lock()
_is_server_owner = False


def port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def prig_already_running(host: str, port: int) -> bool:
    """ ¿Lo que ocupa el puerto es otra instancia de Prig? """
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/workspace", timeout=2) as resp:
            return resp.status == 200 and b'"path"' in resp.read(400)
    except Exception:
        return False


def choose_port(host: str) -> tuple:
    """ Devuelve (puerto, ya_en_marcha). Si Prig ya está abierto, se reutiliza. """
    if port_is_free(host, PREFERRED_PORT):
        return PREFERRED_PORT, False

    if prig_already_running(host, PREFERRED_PORT):
        print(f"ℹ️  Prig ya estaba en marcha en el puerto {PREFERRED_PORT}: se abre una ventana sobre esa instancia.")
        return PREFERRED_PORT, True

    for port in range(PREFERRED_PORT + 1, PREFERRED_PORT + PORT_RANGE):
        if port_is_free(host, port):
            print(f"⚠️  El puerto {PREFERRED_PORT} está ocupado por otro programa; se usará el {port}.")
            return port, False

    raise RuntimeError(
        f"No hay ningún puerto libre entre {PREFERRED_PORT} y {PREFERRED_PORT + PORT_RANGE}."
    )


def start_backend(port: int):
    global _server
    try:
        sys.path.append(os.path.join(ROOT, "backend"))
        from backend.app import app
        config = uvicorn.Config(app, host=HOST, port=port, log_level="error")
        _server = uvicorn.Server(config)
        _server.run()
    except BaseException as exc:  # noqa: BLE001 - hay que ver cualquier fallo, no solo Exception
        _backend_error["exc"] = exc
        _backend_error["traceback"] = traceback.format_exc()


def shutdown_prig(signum=None, frame=None):
    """ Detiene de forma ordenada el servidor, cancela análisis y apaga todos los procesos """
    global _shutting_down
    with _shutdown_lock:
        if _shutting_down:
            return
        _shutting_down = True

    if _is_server_owner:
        print("\n🛑 Cerrando Prig IDE: apagando análisis y procesos en ejecución...")
        if _server is not None:
            _server.should_exit = True
        if _backend_thread is not None and _backend_thread.is_alive():
            _backend_thread.join(timeout=3.0)

        try:
            sys.path.append(os.path.join(ROOT, "backend"))
            from backend.app import cleanup_all_processes
            cleanup_all_processes()
        except Exception:
            pass
        print("✅ Procesos y análisis apagados correctamente.")

    if signum is not None:
        sys.exit(0)


def wait_for_backend(url: str, thread: threading.Thread, timeout: float = 40.0) -> bool:
    """ Espera a que el servidor responda, vigilando además si el hilo ha muerto.

    Sondear a ciegas durante 30 s y rendirse con un mensaje genérico dejaba al
    usuario sin saber si faltaba una dependencia, si el puerto estaba ocupado o si
    había un error de programación.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _backend_error["exc"] is not None:
            return False
        if not thread.is_alive():
            return False
        try:
            with urllib.request.urlopen(url, timeout=1):
                return True
        except urllib.error.HTTPError:
            return True  # responde algo: el servidor está en pie
        except Exception:
            time.sleep(0.2)
    return False


def report_backend_failure(port: int):
    print("\n" + "=" * 60)
    print("❌ Prig no pudo arrancar su servidor interno.")
    print("=" * 60)

    exc = _backend_error["exc"]
    if exc is not None:
        print(f"\nMotivo: {type(exc).__name__}: {exc}\n")
        detalle = _backend_error.get("traceback", "")
        if detalle:
            print("Detalle:")
            print("  " + "\n  ".join(detalle.strip().splitlines()[-12:]))
        if isinstance(exc, ModuleNotFoundError):
            print("\n💡 Falta una dependencia. Ejecuta:")
            print("   .venv/bin/python -m pip install -r requirements.txt")
        elif isinstance(exc, OSError) and "address already in use" in str(exc).lower():
            print(f"\n💡 Otro programa ocupa el puerto {port}. Para ver cuál:")
            print(f"   ss -ltnp | grep :{port}")
    else:
        print("\nEl servidor no respondió a tiempo y no informó de ningún error.")
        print("💡 Prueba a arrancarlo suelto para ver el fallo completo:")
        print("   .venv/bin/python -c \"import sys; sys.path.insert(0,'backend'); import app\"")
    print()


def _blindar_qt() -> None:
    """ Evita que un fallo de Python dentro de un callback de Qt cierre Prig de golpe.

    PyQt6 convierte cualquier excepción no capturada en un callback de Qt en qFatal():
    el proceso aborta sin preguntar y se pierde lo que no estuviera guardado. Así se
    cerraba Prig al pulsar «Insertar en Editor»: navigator.clipboard pide permiso de
    portapapeles, y el manejador de pywebview 6.2 responde con un entero donde PyQt6
    exige el enum (TypeError → abort, reproducido). Con un excepthook propio, PyQt
    solo informa del error; además se corrige ese manejador.
    """
    def informar(tipo, valor, tb):
        print("⚠️ Error en la interfaz (Prig sigue abierto):", file=sys.stderr)
        traceback.print_exception(tipo, valor, tb)
    sys.excepthook = informar

    try:
        from webview.platforms import qt as webview_qt
        from PyQt6.QtWebEngineCore import QWebEnginePage
    except Exception:
        return
    F, P = QWebEnginePage.Feature, QWebEnginePage.PermissionPolicy
    permitidos = {F.MediaAudioCapture, F.MediaVideoCapture, F.MediaAudioVideoCapture, F.ClipboardReadWrite}

    def permiso(self, url, feature):
        politica = P.PermissionGrantedByUser if feature in permitidos else P.PermissionDeniedByUser
        try:
            self.setFeaturePermission(url, feature, politica)
        except Exception:
            traceback.print_exc()

    webview_qt.BrowserView.WebPage.onFeaturePermissionRequested = permiso

    # Descargas («Guardar como…» de los PDF). pywebview las trae apagadas y, encendidas,
    # su manejador llama a download.setPath(), que no existe en Qt 6: se usa el de Qt 6.
    def descargar(self, descarga):
        try:
            from PyQt6.QtWidgets import QFileDialog
            nombre = descarga.suggestedFileName() or "descarga"
            carpeta = next((c for c in (os.path.expanduser("~/Descargas"), os.path.expanduser("~/Downloads"))
                            if os.path.isdir(c)), os.path.expanduser("~"))
            ruta, _ = QFileDialog.getSaveFileName(self, "Guardar como", os.path.join(carpeta, nombre))
            if ruta:
                descarga.setDownloadDirectory(os.path.dirname(ruta))
                descarga.setDownloadFileName(os.path.basename(ruta))
                descarga.accept()
            else:
                descarga.cancel()
        except Exception:
            traceback.print_exc()

    webview_qt.BrowserView.on_download_requested = descargar
    try:
        import webview
        webview.settings["ALLOW_DOWNLOADS"] = True
    except Exception:
        pass


def open_gui(url: str) -> bool:
    """ Intenta la ventana nativa. Devuelve False para caer al navegador. """
    try:
        import webview
    except Exception as e:
        print(f"⚠️ pywebview no disponible ({e}).")
        return False

    _blindar_qt()

    # Asignar identificador para que la ventana nativa reciba WM_CLASS="Prig-IDE"
    # y el dock de Ubuntu/GNOME muestre el icono del programa en vez de la tuerca gris
    sys.argv[0] = "Prig-IDE"

    icon_path = os.path.join(ROOT, "assets", "icon.svg")

    try:
        window = webview.create_window(
            title="Prig IDE - Editor & Tutor IA Local",
            url=url,
            width=1280, height=800,
            min_size=(450, 400),
            resizable=True,
        )
        try:
            window.events.closing += lambda *a, **k: shutdown_prig()
        except Exception:
            pass
    except Exception as e:
        print(f"⚠️ No se pudo crear la ventana: {e}")
        return False

    # Se prueban los backends gráficos en orden en vez de fijar "qt": si Qt falla,
    # antes se caía al navegador aunque GTK estuviera disponible.
    for gui in ("qt", "gtk", None):
        try:
            if gui:
                webview.start(gui=gui, icon=icon_path)
            else:
                webview.start(icon=icon_path)
            return True
        except Exception as e:
            print(f"⚠️ Interfaz nativa '{gui or 'automática'}' no disponible: {e}")
    return False


def main():
    global _is_server_owner, _backend_thread

    # Registrar manejadores de señales y salida
    try:
        signal.signal(signal.SIGINT, shutdown_prig)
        signal.signal(signal.SIGTERM, shutdown_prig)
    except Exception:
        pass
    atexit.register(shutdown_prig)

    try:
        port, ya_en_marcha = choose_port(HOST)
    except RuntimeError as e:
        print(f"❌ {e}")
        return 1

    target_url = f"http://{HOST}:{port}"

    if not ya_en_marcha:
        _is_server_owner = True
        _backend_thread = threading.Thread(target=start_backend, args=(port,), daemon=True)
        _backend_thread.start()

        if not wait_for_backend(target_url, _backend_thread):
            report_backend_failure(port)
            return 1

    print(f"✅ Servidor interno listo en {target_url}")

    if open_gui(target_url):
        shutdown_prig()
        return 0

    # Sin ventana nativa, el navegador. Nunca se sale sin dar una vía de acceso:
    # antes un fallo del backend terminaba el programa sin abrir absolutamente nada.
    print("💡 Abriendo Prig IDE en el navegador...")
    try:
        webbrowser.open(target_url)
    except Exception as e:
        print(f"⚠️ Tampoco se pudo abrir el navegador ({e}).")
    print(f"🌐 Prig IDE activo en: {target_url}")
    print("Presiona Ctrl+C para salir.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        shutdown_prig()
    return 0


if __name__ == "__main__":
    sys.exit(main())
