"""
Los archivos del usuario: qué rutas se pueden tocar, el árbol del explorador, leer (también cuadernos), escribir,
crear y borrar, y la carpeta de trabajo y la segunda carpeta guardadas en ~/.prig_config.json.

La lógica está en Rust (backend-rust/crates/prig-plataforma, archivos.rs y espacio.rs) y no guarda estado: la
carpeta de trabajo, la segunda carpeta y la ruta de la configuración son atributos de este objeto (las pruebas los
cambian) y llegan a Rust en cada llamada.
"""
import os
from typing import List, Dict, Any


def _rs():
    from nativo_rust import rust
    return rust().archivos


class FileManager:
    # Única raíz fuera del workspace a la que la aplicación necesita acceder.
    #
    # Antes también se admitía tempfile.gettempdir() entero, lo que dejaba /tmp
    # completo legible y escribible desde la API. Nada lo necesitaba: el runner y
    # el kernel crean sus temporales por su cuenta, sin pasar por aquí.
    EXTRA_ALLOWED_ROOTS = (
        os.path.expanduser('~/.prig_books'),
    )

    def __init__(self, base_dir: str = None):
        self.config_path = os.path.expanduser('~/.prig_config.json')
        if base_dir:
            self.base_dir = os.path.abspath(base_dir)
        else:
            self.base_dir = self._load_last_workspace()
        # La segunda carpeta del explorador (para copiar código de una a otra); solo con el workspace del usuario
        self.segunda_dir = None if base_dir else self._leer_config().get("segunda_carpeta")
        if not isinstance(self.segunda_dir, str) or not os.path.isdir(self.segunda_dir):
            self.segunda_dir = None

    def allowed_roots(self) -> List[str]:
        # Tus repositorios de Prig Hub (perfil y packs) se pueden editar a mano en el editor.
        # Los que sigues NO: son de otros y se actualizan solo revisando sus cambios.
        from hub.servicio import ruta_base
        propios = os.path.join(ruta_base(), "propios")
        raices = [self.base_dir] + [os.path.abspath(r) for r in self.EXTRA_ALLOWED_ROOTS] + [os.path.abspath(propios)]
        if self.segunda_dir:
            raices.append(self.segunda_dir)
        return raices

    def is_path_allowed(self, abs_path: str) -> bool:
        """ True solo si la ruta cae dentro del workspace o de una raíz permitida.

        Sin esta comprobación cualquier página web abierta por el usuario podía leer,
        sobrescribir o borrar archivos arbitrarios a través de la API local.
        """
        return _rs().permitida(abs_path, self.allowed_roots())

    def resolve(self, path: str) -> str:
        """ Normaliza una ruta relativa al workspace y verifica que sea accesible (PermissionError si no) """
        return _rs().resolver(path or "", self.base_dir, self.allowed_roots())

    @property
    def current_workspace(self) -> str:
        return self.base_dir

    def _load_last_workspace(self) -> str:
        return _rs().cargar_ultima(self.config_path)

    def _save_last_workspace(self, path: str):
        _rs().guardar_clave(self.config_path, "last_workspace", path)

    def _leer_config(self) -> Dict[str, Any]:
        return _rs().leer_config(self.config_path)

    def set_segunda_dir(self, path: str = None) -> Dict[str, Any]:
        """ Fija la segunda carpeta del explorador (o la quita con None) y la guarda en la config """
        if path:
            abs_path, res = _rs().carpeta(path)
            if abs_path is None:
                return res
        else:
            abs_path = None
        self.segunda_dir = abs_path
        _rs().guardar_clave(self.config_path, "segunda_carpeta", abs_path)
        return _rs().respuesta_segunda(abs_path)

    def set_base_dir(self, path: str) -> Dict[str, Any]:
        abs_path, res = _rs().carpeta(path)
        if abs_path is not None:
            self.base_dir = abs_path
            self._save_last_workspace(abs_path)
        return res

    def browse_folder_native(self) -> Dict[str, Any]:
        """ Abre el selector de carpetas del sistema (zenity, o tkinter si no hay) """
        selected = self.elegir_carpeta_nativa()
        if selected:
            return self.set_base_dir(selected)
        return {"error": "No se pudo abrir el diálogo nativo de carpetas"}

    def elegir_carpeta_nativa(self, titulo: str = "Seleccionar Carpeta de Proyecto - Prig IDE"):
        """ La carpeta que elige el usuario en el diálogo nativo (zenity o tkinter), o None """
        selected = _rs().elegir_con_zenity(titulo)
        if selected:
            return selected

        # Si no hay zenity: el diálogo de tkinter (solo existe en Python)
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            selected = filedialog.askdirectory(title=titulo, initialdir=self.base_dir)
            root.destroy()
            if selected and os.path.isdir(selected):
                return selected
        except Exception:
            pass
        return None

    def get_file_tree(self, path: str = None, max_depth: int = 6, current_depth: int = 0) -> List[Dict[str, Any]]:
        return _rs().arbol(path, self.base_dir, self.allowed_roots(), max_depth, current_depth)

    def read_file(self, file_path: str) -> Dict[str, Any]:
        return _rs().leer(file_path or "", self.base_dir, self.allowed_roots())

    def read_notebook_structured(self, json_str: str, file_path: str) -> Dict[str, Any]:
        """ Retorna la estructura de celdas formateada de un Jupyter Notebook """
        return _rs().cuaderno(json_str, file_path)

    def write_file(self, file_path: str, content: str) -> Dict[str, Any]:
        return _rs().escribir(file_path or "", content, self.base_dir, self.allowed_roots())

    def create_item(self, target_path: str, is_dir: bool = False) -> Dict[str, Any]:
        return _rs().crear(target_path or "", bool(is_dir), self.base_dir, self.allowed_roots())

    def delete_item(self, target_path: str) -> Dict[str, Any]:
        # Nunca permite borrar la raíz del workspace o de la biblioteca de un tirón
        return _rs().borrar(target_path or "", self.base_dir, self.allowed_roots())
