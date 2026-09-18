import os
import sys
import webview

def launch():
    sys.argv[0] = "Prig-IDE"
    target_url = "http://127.0.0.1:8000/static/note.html"
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.svg")

    window = webview.create_window(
        title="Note - Bloc de Notas (Prig IDE)",
        url=target_url,
        width=840,
        height=590,
        min_size=(450, 400),
        resizable=True
    )
    
    try:
        webview.start(gui="qt", icon=icon_path)
    except Exception:
        try:
            webview.start(gui="gtk", icon=icon_path)
        except Exception:
            webview.start(icon=icon_path)

if __name__ == '__main__':
    launch()
