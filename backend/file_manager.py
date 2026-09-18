import os
import json
import shutil
import subprocess
from typing import List, Dict, Any

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

    def allowed_roots(self) -> List[str]:
        return [self.base_dir] + [os.path.abspath(r) for r in self.EXTRA_ALLOWED_ROOTS]

    def is_path_allowed(self, abs_path: str) -> bool:
        """ True solo si la ruta cae dentro del workspace o de una raíz permitida.

        Sin esta comprobación cualquier página web abierta por el usuario podía leer,
        sobrescribir o borrar archivos arbitrarios a través de la API local.
        """
        abs_path = os.path.abspath(abs_path)
        for root in self.allowed_roots():
            try:
                if os.path.commonpath([abs_path, root]) == root:
                    return True
            except ValueError:
                # Rutas en volúmenes distintos: commonpath lanza ValueError
                continue
        return False

    def resolve(self, path: str) -> str:
        """ Normaliza una ruta relativa al workspace y verifica que sea accesible """
        if not path:
            raise PermissionError("Ruta no especificada")
        abs_path = os.path.abspath(path if os.path.isabs(path) else os.path.join(self.base_dir, path))
        if not self.is_path_allowed(abs_path):
            raise PermissionError(
                f"Acceso denegado: '{abs_path}' está fuera de la carpeta de trabajo."
            )
        return abs_path

    @property
    def current_workspace(self) -> str:
        return self.base_dir


    def _load_last_workspace(self) -> str:
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    config = json.load(f)
                    last_dir = config.get("last_workspace")
                    if last_dir and os.path.isdir(last_dir):
                        return last_dir
        except Exception:
            pass
        return os.getcwd()

    def _save_last_workspace(self, path: str):
        try:
            config = {}
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    config = json.load(f)
            config["last_workspace"] = path
            with open(self.config_path, 'w') as f:
                json.dump(config, f)
        except Exception:
            pass

    def set_base_dir(self, path: str) -> Dict[str, Any]:
        abs_path = os.path.abspath(os.path.expanduser(path))
        if os.path.isdir(abs_path):
            self.base_dir = abs_path
            self._save_last_workspace(abs_path)
            return {"success": True, "path": abs_path, "name": os.path.basename(abs_path) or abs_path}
        return {"error": f"El directorio no existe: {path}"}

    def browse_folder_native(self) -> Dict[str, Any]:
        """ Abre el selector de archivos nativo de Ubuntu mediante zenity, kdialog o python tkinter """
        # Intentar zenity primero (estándar en Ubuntu GNOME)
        try:
            res = subprocess.run(
                ["zenity", "--file-selection", "--directory", "--title=Seleccionar Carpeta de Proyecto - Prig IDE"],
                capture_output=True, text=True, check=True
            )
            selected = res.stdout.strip()
            if selected and os.path.isdir(selected):
                return self.set_base_dir(selected)
        except Exception:
            pass

        # Fallback a tkinter dialog
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            selected = filedialog.askdirectory(title="Seleccionar Carpeta de Proyecto - Prig IDE", initialdir=self.base_dir)
            root.destroy()
            if selected and os.path.isdir(selected):
                return self.set_base_dir(selected)
        except Exception:
            pass

        return {"error": "No se pudo abrir el diálogo nativo de carpetas"}

    def get_file_tree(self, path: str = None, max_depth: int = 6, current_depth: int = 0) -> List[Dict[str, Any]]:
        target_dir = os.path.abspath(path) if path else self.base_dir
        if not os.path.exists(target_dir) or not os.path.isdir(target_dir) or current_depth >= max_depth:
            return []
        if not self.is_path_allowed(target_dir):
            return []

        ignored = {
            '__pycache__', 'node_modules', 'venv', '.venv', 'env', '.env',
            '.git', '.github', '.ipynb_checkpoints', 'dist', 'build',
            '.cache', 'site-packages', '.idea', '.vscode', '.gemini'
        }

        tree = []
        try:
            entries = sorted(os.listdir(target_dir), key=lambda x: (not os.path.isdir(os.path.join(target_dir, x)), x.lower()))
            for entry in entries:
                if (entry.startswith('.') and entry not in ['.gitignore', '.env.example']) or entry in ignored:
                    continue
                full_path = os.path.join(target_dir, entry)
                is_dir = os.path.isdir(full_path)
                tree.append({
                    "name": entry,
                    "path": full_path,
                    "is_dir": is_dir,
                    "children": self.get_file_tree(full_path, max_depth=max_depth, current_depth=current_depth + 1) if is_dir else None
                })
        except Exception as e:
            print(f"Error leyendo dir {target_dir}: {e}")
        return tree

    def read_file(self, file_path: str) -> Dict[str, Any]:
        try:
            abs_path = self.resolve(file_path)
        except PermissionError as e:
            return {"error": str(e)}
        if not os.path.isfile(abs_path):
            return {"error": f"Archivo no encontrado: {file_path}"}
        
        ext = os.path.splitext(abs_path)[1].lower()
        try:
            with open(abs_path, 'r', encoding='utf-8', errors='replace') as f:
                raw_content = f.read()

            if ext == '.ipynb':
                notebook_data = self.read_notebook_structured(raw_content, abs_path)
                return {
                    "path": abs_path,
                    "name": os.path.basename(abs_path),
                    "content": raw_content,
                    "notebook_data": notebook_data,
                    "is_notebook": True
                }

            return {
                "path": abs_path,
                "name": os.path.basename(abs_path),
                "content": raw_content,
                "is_notebook": False
            }
        except Exception as e:
            return {"error": str(e)}

    def read_notebook_structured(self, json_str: str, file_path: str) -> Dict[str, Any]:
        """ Retorna la estructura de celdas formateada de un Jupyter Notebook """
        try:
            data = json.loads(json_str)
            raw_cells = data.get("cells", [])
            cells = []

            for idx, cell in enumerate(raw_cells, 1):
                cell_type = cell.get("cell_type", "code")
                source = cell.get("source", [])
                source_str = "".join(source) if isinstance(source, list) else str(source)
                
                # Procesar adjuntos (attachments) de celdas Markdown
                attachments = cell.get("attachments", {})
                if attachments and isinstance(attachments, dict):
                    for attach_name, mime_dict in attachments.items():
                        if isinstance(mime_dict, dict):
                            for mime_type, b64_val in mime_dict.items():
                                clean_b64 = "".join(b64_val) if isinstance(b64_val, list) else str(b64_val)
                                clean_b64 = clean_b64.replace("\n", "").replace("\r", "").strip()
                                data_uri = f"data:{mime_type};base64,{clean_b64}"
                                source_str = source_str.replace(f"attachment:{attach_name}", data_uri)

                outputs = []
                for out in cell.get("outputs", []):
                    output_type = out.get("output_type", "")
                    if output_type == "stream":
                        text = "".join(out.get("text", []))
                        outputs.append({"type": "stream", "text": text, "name": out.get("name", "stdout")})
                    elif output_type == "execute_result" or output_type == "display_data":
                        data_dict = out.get("data", {})
                        if "text/html" in data_dict:
                            text = "".join(data_dict["text/html"]) if isinstance(data_dict["text/html"], list) else data_dict["text/html"]
                            outputs.append({"type": "html", "text": text})
                        else:
                            img_found = False
                            for mime in ["image/png", "image/jpeg", "image/jpg", "image/svg+xml", "image/gif"]:
                                if mime in data_dict:
                                    img_data = "".join(data_dict[mime]) if isinstance(data_dict[mime], list) else data_dict[mime]
                                    outputs.append({"type": "image", "data": img_data, "mime": mime})
                                    img_found = True
                                    break
                            if not img_found and "text/plain" in data_dict:
                                text = "".join(data_dict["text/plain"]) if isinstance(data_dict["text/plain"], list) else data_dict["text/plain"]
                                outputs.append({"type": "text", "text": text})
                    elif output_type == "error":
                        ename = out.get("ename", "")
                        evalue = out.get("evalue", "")
                        traceback = "\n".join(out.get("traceback", []))
                        outputs.append({"type": "error", "text": f"{ename}: {evalue}\n{traceback}"})

                cells.append({
                    "id": f"cell_{idx}",
                    "index": idx,
                    "type": cell_type,
                    "source": source_str,
                    "execution_count": cell.get("execution_count", None),
                    "outputs": outputs
                })

            return {
                "path": file_path,
                "name": os.path.basename(file_path),
                "cells": cells
            }
        except Exception as e:
            return {"error": f"Error parseando notebook: {str(e)}", "cells": []}

    def write_file(self, file_path: str, content: str) -> Dict[str, Any]:
        try:
            abs_path = self.resolve(file_path)
        except PermissionError as e:
            return {"error": str(e)}
        try:
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return {"success": True, "path": abs_path}
        except Exception as e:
            return {"error": str(e)}

    def create_item(self, target_path: str, is_dir: bool = False) -> Dict[str, Any]:
        try:
            abs_path = self.resolve(target_path)
        except PermissionError as e:
            return {"error": str(e)}
        try:
            if is_dir:
                os.makedirs(abs_path, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                if not os.path.exists(abs_path):
                    with open(abs_path, 'w', encoding='utf-8') as f:
                        f.write('')
            return {"success": True, "path": abs_path}
        except Exception as e:
            return {"error": str(e)}

    def delete_item(self, target_path: str) -> Dict[str, Any]:
        try:
            abs_path = self.resolve(target_path)
        except PermissionError as e:
            return {"error": str(e)}

        # Nunca permitir borrar la raíz del workspace o de la biblioteca de un tirón
        if abs_path in self.allowed_roots():
            return {"error": "No se puede eliminar la carpeta raíz del espacio de trabajo."}

        try:
            if os.path.isdir(abs_path):
                shutil.rmtree(abs_path)
            elif os.path.isfile(abs_path):
                os.remove(abs_path)
            else:
                return {"error": f"No existe: {target_path}"}
            return {"success": True, "path": abs_path}
        except Exception as e:
            return {"error": str(e)}
