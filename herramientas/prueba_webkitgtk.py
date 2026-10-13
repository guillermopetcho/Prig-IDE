#!/usr/bin/python3
"""Prueba de la interfaz de Prig en WebKitGTK: el motor web que usa la ventana de Rust (wry/Tauri) en Linux. La
ventana actual (pywebview + QtWebEngine) es Chromium, así que hay que comprobar que la interfaz funciona igual antes
de cambiarla (docs/plan-prig-rust.md, F0 y F9).

No muestra nada: la vista va en una ventana fuera de pantalla (Gtk.OffscreenWindow). Junta los errores de
JavaScript desde el arranque, mira las funciones del navegador que usa el frontend y guarda una captura.

    /usr/bin/python3 herramientas/prueba_webkitgtk.py http://127.0.0.1:18000/ captura.png [segundos]

Usa el Python del sistema (necesita gi con WebKit2 4.1, que viene con el escritorio de Ubuntu).
"""
import json
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import GLib, Gtk, WebKit2  # noqa: E402

url, salida_png = sys.argv[1], sys.argv[2]
espera = float(sys.argv[3]) if len(sys.argv) > 3 else 15.0

CAPTURA = """
window.__qa = {errores: [], rechazos: []};
window.addEventListener('error', e => window.__qa.errores.push(String(e.message) + ' @ ' + (e.filename || '') + ':' + (e.lineno || '')));
window.addEventListener('unhandledrejection', e => window.__qa.rechazos.push(String(e.reason && (e.reason.stack || e.reason.message || e.reason))));
const _consolaError = console.error;
console.error = function (...a) { window.__qa.errores.push('console.error: ' + a.map(String).join(' ')); return _consolaError.apply(console, a); };
"""

ESTADO = """JSON.stringify({
  errores: window.__qa.errores.slice(0, 60),
  rechazos: window.__qa.rechazos.slice(0, 60),
  motorGrafico: window.motorGraficoFachada && window.motorGraficoFachada.stats && window.motorGraficoFachada.stats.modoActivo,
  funciones: {
    OffscreenCanvas: typeof OffscreenCanvas, WebAssembly: typeof WebAssembly, structuredClone: typeof structuredClone,
    ResizeObserver: typeof ResizeObserver, IntersectionObserver: typeof IntersectionObserver,
    portapapeles: !!(navigator.clipboard && navigator.clipboard.writeText), requestIdleCallback: typeof requestIdleCallback,
    BroadcastChannel: typeof BroadcastChannel, WebSocket: typeof WebSocket, Worker: typeof Worker,
    cssHas: CSS.supports('selector(:has(a))'), cssContainer: CSS.supports('container-type: inline-size'),
    backdropFilter: CSS.supports('backdrop-filter: blur(2px)') || CSS.supports('-webkit-backdrop-filter: blur(2px)')
  },
  titulo: document.title,
  nodos: document.querySelectorAll('*').length,
  texto: (document.body && document.body.innerText || '').slice(0, 200)
})"""

resultado = {"version_webkit": f"{WebKit2.get_major_version()}.{WebKit2.get_minor_version()}.{WebKit2.get_micro_version()}"}

manager = WebKit2.UserContentManager()
manager.add_script(WebKit2.UserScript(CAPTURA, WebKit2.UserContentInjectedFrames.TOP_FRAME,
                                      WebKit2.UserScriptInjectionTime.START, None, None))
vista = WebKit2.WebView.new_with_user_content_manager(manager)
ajustes = vista.get_settings()
ajustes.set_enable_webgl(True)
ventana = Gtk.OffscreenWindow()
ventana.set_default_size(1280, 800)
ventana.add(vista)
ventana.show_all()


def terminar():
    print(json.dumps(resultado, ensure_ascii=False, indent=1))
    Gtk.main_quit()
    return False


def al_capturar(v, res, _):
    try:
        v.get_snapshot_finish(res).write_to_png(salida_png)
        resultado["captura"] = salida_png
    except Exception as e:  # noqa: BLE001 — sin cairo para Python no hay captura, el resto vale igual
        resultado["captura"] = f"sin captura: {e}"
    terminar()


def al_evaluar(v, res, _):
    try:
        resultado.update(json.loads(v.evaluate_javascript_finish(res).to_string()))
    except Exception as e:  # noqa: BLE001
        resultado["error_evaluar"] = str(e)
    v.get_snapshot(WebKit2.SnapshotRegion.VISIBLE, WebKit2.SnapshotOptions.NONE, None, al_capturar, None)


def evaluar():
    vista.evaluate_javascript(ESTADO, -1, None, None, None, al_evaluar, None)
    return False


def al_cargar(v, evento):
    if evento == WebKit2.LoadEvent.FINISHED:
        resultado["cargado"] = True


vista.connect("load-changed", al_cargar)
vista.load_uri(url)
GLib.timeout_add(int(espera * 1000), evaluar)
GLib.timeout_add(int((espera + 30) * 1000), lambda: (resultado.setdefault("aviso", "tiempo agotado"), terminar()))
Gtk.main()
