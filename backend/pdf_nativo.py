"""
Leer PDF con PDFium (el motor de PDF de Chrome), en Rust: backend-rust/crates/prig-biblioteca, pdf.rs.

Medido con un libro de 864 páginas: 1,7 s contra ~14 s de pypdf, con el 99,5 % de las palabras iguales y ninguna
página perdida (donde difieren, PDFium acierta más). La biblioteca va en lib/pdfium (herramientas/instalar_pdfium.sh)
o donde diga PRIG_PDFIUM. Si no está, o un PDF no se puede abrir con ella, quien llama sigue con pypdf.
"""
import os
import threading
from typing import Any, Optional

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_cerrojo = threading.Lock()
_estado: dict = {}


def ruta_biblioteca() -> str:
    return os.environ.get("PRIG_PDFIUM") or os.path.join(_RAIZ, "lib", "pdfium", "libpdfium.so")


def lector() -> Optional[Any]:
    """ El módulo `prig_nativo.pdf` con PDFium cargado, o None si no se puede """
    with _cerrojo:
        if "lector" not in _estado:
            try:
                from nativo_rust import rust
                modulo = rust().pdf
                ruta = ruta_biblioteca()
                if not os.path.isfile(ruta):
                    raise FileNotFoundError(ruta)
                modulo.cargar(ruta)
                _estado["lector"] = modulo
            except Exception as e:
                print(f"PDFium no disponible ({e}); se usa pypdf.")
                _estado["lector"] = None
        return _estado["lector"]
