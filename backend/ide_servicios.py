"""
Servicios de IDE sobre la carpeta de trabajo: lo que todo editor de código trae.

  · listar archivos (para "Ir a archivo…", Ctrl+P)
  · buscar y reemplazar en todos los archivos (Ctrl+Shift+F / Ctrl+Shift+H)
  · renombrar, duplicar y mover
  · problemas de sintaxis de Python (subrayado rojo y F8)
  · carpetas recientes
  · mostrar en el explorador del sistema

Todo pasa por FileManager.resolve(): nada sale de la carpeta de trabajo ni de las
raíces permitidas. Se ignoran las mismas carpetas que el árbol (.git, venv,
node_modules…), así la búsqueda encuentra lo que el usuario ve.

Todo está en Rust (backend-rust/crates/prig-plataforma, ide.rs; las expresiones regulares, con la sintaxis de `re`,
en regex_py.rs), salvo los problemas de sintaxis de Python: los ve el compilador de Python (Python como herramienta).
"""

import ast
import io
import tokenize
from typing import Any, Dict, List, Optional


def _rs():
    from nativo_rust import rust
    return rust().ide


IGNORADAS = set(_rs().IGNORADAS)
MAX_ARCHIVOS = _rs().MAX_ARCHIVOS
MAX_BYTES_BUSQUEDA = _rs().MAX_BYTES_BUSQUEDA
MAX_COINCIDENCIAS = _rs().MAX_COINCIDENCIAS
MAX_RECIENTES = _rs().MAX_RECIENTES

ErrorIDE = _rs().ErrorIDE


# ===========================================================================

class ServiciosIDE:
    def __init__(self, file_mgr):
        self.fm = file_mgr

    # ------------------------------------------------------------ archivos
    def listar(self, limite: int = MAX_ARCHIVOS) -> Dict[str, Any]:
        return _rs().listar(self.fm.base_dir, limite)

    def renombrar(self, ruta: str, destino: str) -> Dict[str, Any]:
        """ `destino` puede ser un nombre (mismo directorio) o una ruta relativa/absoluta """
        return _rs().renombrar(ruta or "", destino, self.fm.base_dir, self.fm.allowed_roots())

    def duplicar(self, ruta: str) -> Dict[str, Any]:
        return _rs().duplicar(ruta or "", self.fm.base_dir, self.fm.allowed_roots())

    # ------------------------------------------------------------ búsqueda
    def buscar(self, consulta: str, regex: bool = False, mayusculas: bool = False,
               palabra: bool = False, incluir: str = "", excluir: str = "",
               limite: int = MAX_COINCIDENCIAS) -> Dict[str, Any]:
        return _rs().buscar(self.fm.base_dir, consulta or "", bool(regex), bool(mayusculas), bool(palabra),
                            incluir or "", excluir or "", limite)

    def reemplazar(self, consulta: str, reemplazo: str, regex: bool = False,
                   mayusculas: bool = False, palabra: bool = False, incluir: str = "",
                   excluir: str = "", solo: Optional[List[str]] = None) -> Dict[str, Any]:
        """ Reemplaza en disco. `solo` limita a esas rutas (las que el usuario dejó
        marcadas en los resultados, sin las que tienen cambios sin guardar). """
        return _rs().reemplazar(self.fm.base_dir, self.fm.allowed_roots(), consulta or "", reemplazo, bool(regex),
                                bool(mayusculas), bool(palabra), incluir or "", excluir or "",
                                list(solo) if solo is not None else None)

    # ------------------------------------------------------------ problemas
    @staticmethod
    def problemas_python(codigo: str) -> List[Dict[str, Any]]:
        """ Errores de sintaxis e indentación: lo que impide ejecutar el archivo.
        Sin dependencias: el propio compilador de Python. """
        problemas = []
        try:
            ast.parse(codigo)
        except SyntaxError as e:
            linea = e.lineno or 1
            col = e.offset or 1
            fin_col = getattr(e, "end_offset", None) or col + 1
            fin_linea = getattr(e, "end_lineno", None) or linea
            if fin_linea == linea and fin_col <= col:
                fin_col = col + 1
            problemas.append({"linea": linea, "col": col, "fin_linea": fin_linea,
                              "fin_col": fin_col, "gravedad": "error",
                              "mensaje": f"{type(e).__name__}: {e.msg}"})
        except ValueError as e:          # p. ej. bytes nulos
            problemas.append({"linea": 1, "col": 1, "fin_linea": 1, "fin_col": 2,
                              "gravedad": "error", "mensaje": str(e)})
        else:
            # Mezcla de tabuladores y espacios: compila, pero es una trampa
            try:
                list(tokenize.generate_tokens(io.StringIO(codigo).readline))
            except (tokenize.TokenError, IndentationError) as e:
                problemas.append({"linea": 1, "col": 1, "fin_linea": 1, "fin_col": 2,
                                  "gravedad": "aviso", "mensaje": str(e)})
        return problemas

    def problemas(self, lenguaje: str, codigo: str) -> List[Dict[str, Any]]:
        if lenguaje == "python":
            return self.problemas_python(codigo)
        return []

    # ------------------------------------------------------------ recientes y proyectos
    def recientes(self) -> List[Dict[str, Any]]:
        return _rs().recientes(self.fm.config_path, self.fm.base_dir)

    def anotar_reciente(self, ruta: str):
        _rs().anotar_reciente(self.fm.config_path, ruta)

    def olvidar_recientes(self):
        _rs().olvidar_recientes(self.fm.config_path)

    # ------------------------------------------------------------ proyectos guardados
    def proyectos_guardados(self) -> List[Dict[str, Any]]:
        """ El actual primero, luego los existentes, por nombre """
        return _rs().proyectos_guardados(self.fm.config_path, self.fm.base_dir)

    def guardar_proyecto(self, ruta: str, nombre: Optional[str] = None, origen: str = "biblioteca") -> Dict[str, Any]:
        return _rs().guardar_proyecto(self.fm.config_path, ruta, nombre, origen)

    def eliminar_proyecto_guardado(self, ruta: str) -> Dict[str, Any]:
        return _rs().eliminar_proyecto(self.fm.config_path, ruta)

    # ------------------------------------------------------------ explorar directorios
    def listar_directorios(self, ruta: Optional[str] = None) -> Dict[str, Any]:
        return _rs().listar_directorios(ruta, self.fm.base_dir)

    # ------------------------------------------------------------ sistema
    def mostrar_en_sistema(self, ruta: str) -> Dict[str, Any]:
        return _rs().mostrar_en_sistema(ruta or "", self.fm.base_dir, self.fm.allowed_roots())
