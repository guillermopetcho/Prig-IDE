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
"""

import ast
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tokenize
import io
from typing import Any, Dict, List, Optional

IGNORADAS = {
    "__pycache__", "node_modules", "venv", ".venv", "env", ".git", ".github",
    ".ipynb_checkpoints", "dist", "build", ".cache", "site-packages", ".idea",
    ".vscode", ".gemini", ".mypy_cache", ".pytest_cache", ".tox",
}
MAX_ARCHIVOS = 20000
MAX_BYTES_BUSQUEDA = 2 * 1024 * 1024
MAX_COINCIDENCIAS = 5000
MAX_RECIENTES = 12


class ErrorIDE(Exception):
    pass


def _recorrer(raiz: str, ocultos: bool = False):
    for carpeta, subdirs, archivos in os.walk(raiz):
        subdirs[:] = sorted(d for d in subdirs
                            if d not in IGNORADAS and (ocultos or not d.startswith(".")))
        for nombre in sorted(archivos):
            if not ocultos and nombre.startswith(".") and nombre not in (".gitignore", ".env.example"):
                continue
            yield os.path.join(carpeta, nombre)


def _coincide_patrones(relativa: str, incluir: List[str], excluir: List[str]) -> bool:
    def casa(patron: str) -> bool:
        patron = patron.strip()
        if not patron:
            return False
        # "src/" o "src" casan con todo lo que hay dentro; "*.py" con el nombre
        if "/" not in patron and not any(c in patron for c in "*?["):
            return patron in relativa.split("/")
        return (fnmatch.fnmatch(relativa, patron) or fnmatch.fnmatch(os.path.basename(relativa), patron)
                or fnmatch.fnmatch(relativa, f"*/{patron}") or relativa.startswith(patron.rstrip("/") + "/"))
    if incluir and not any(casa(p) for p in incluir):
        return False
    return not any(casa(p) for p in excluir)


def _patrones(texto: Optional[str]) -> List[str]:
    return [p.strip() for p in (texto or "").split(",") if p.strip()]


# ===========================================================================

class ServiciosIDE:
    def __init__(self, file_mgr):
        self.fm = file_mgr

    # ------------------------------------------------------------ archivos
    def listar(self, limite: int = MAX_ARCHIVOS) -> Dict[str, Any]:
        raiz = self.fm.base_dir
        salida, truncado = [], False
        for ruta in _recorrer(raiz):
            if len(salida) >= limite:
                truncado = True
                break
            salida.append({"path": ruta, "rel": os.path.relpath(ruta, raiz).replace(os.sep, "/")})
        return {"raiz": raiz, "archivos": salida, "truncado": truncado}

    def renombrar(self, ruta: str, destino: str) -> Dict[str, Any]:
        """ `destino` puede ser un nombre (mismo directorio) o una ruta relativa/absoluta """
        origen = self.fm.resolve(ruta)
        if not os.path.exists(origen):
            raise ErrorIDE(f"No existe: {ruta}")
        if origen in self.fm.allowed_roots():
            raise ErrorIDE("No se puede renombrar la carpeta raíz del espacio de trabajo.")
        if "/" not in destino and os.sep not in destino:
            destino = os.path.join(os.path.dirname(origen), destino)
        final = self.fm.resolve(destino)
        if final == origen:
            return {"success": True, "path": final, "anterior": origen}
        if os.path.exists(final):
            raise ErrorIDE(f"Ya existe: {os.path.relpath(final, self.fm.base_dir)}")
        if os.path.isdir(origen) and (final + os.sep).startswith(origen + os.sep):
            raise ErrorIDE("No se puede mover una carpeta dentro de sí misma.")
        os.makedirs(os.path.dirname(final), exist_ok=True)
        shutil.move(origen, final)
        return {"success": True, "path": final, "anterior": origen, "es_dir": os.path.isdir(final)}

    def duplicar(self, ruta: str) -> Dict[str, Any]:
        origen = self.fm.resolve(ruta)
        if not os.path.exists(origen):
            raise ErrorIDE(f"No existe: {ruta}")
        base, ext = os.path.splitext(origen) if os.path.isfile(origen) else (origen, "")
        n = 1
        while True:
            candidato = f"{base} copia{'' if n == 1 else f' {n}'}{ext}"
            if not os.path.exists(candidato):
                break
            n += 1
        final = self.fm.resolve(candidato)
        if os.path.isdir(origen):
            shutil.copytree(origen, final)
        else:
            shutil.copy2(origen, final)
        return {"success": True, "path": final}

    # ------------------------------------------------------------ búsqueda
    def _expresion(self, consulta: str, regex: bool, mayusculas: bool, palabra: bool):
        if not consulta:
            raise ErrorIDE("Escribe qué buscar.")
        patron = consulta if regex else re.escape(consulta)
        if palabra:
            patron = rf"(?<!\w){patron}(?!\w)"
        try:
            return re.compile(patron, 0 if mayusculas else re.IGNORECASE)
        except re.error as e:
            raise ErrorIDE(f"Expresión regular no válida: {e}")

    def _archivos_texto(self, incluir: str, excluir: str):
        raiz = self.fm.base_dir
        inc, exc = _patrones(incluir), _patrones(excluir)
        for ruta in _recorrer(raiz):
            rel = os.path.relpath(ruta, raiz).replace(os.sep, "/")
            if not _coincide_patrones(rel, inc, exc):
                continue
            try:
                if os.path.getsize(ruta) > MAX_BYTES_BUSQUEDA:
                    continue
                with open(ruta, "rb") as f:
                    datos = f.read()
            except OSError:
                continue
            if b"\x00" in datos[:8192]:
                continue                       # binario
            try:
                texto = datos.decode("utf-8")
            except UnicodeDecodeError:
                continue                       # no se reescribiría bien: se salta
            yield ruta, rel, texto

    def buscar(self, consulta: str, regex: bool = False, mayusculas: bool = False,
               palabra: bool = False, incluir: str = "", excluir: str = "",
               limite: int = MAX_COINCIDENCIAS) -> Dict[str, Any]:
        expr = self._expresion(consulta, regex, mayusculas, palabra)
        resultados, total, truncado, revisados = [], 0, False, 0
        for ruta, rel, texto in self._archivos_texto(incluir, excluir):
            revisados += 1
            coincidencias = []
            for n, linea in enumerate(texto.splitlines(), 1):
                for m in expr.finditer(linea):
                    if m.start() == m.end():
                        continue
                    coincidencias.append({
                        "linea": n, "col": m.start() + 1, "fin": m.end() + 1,
                        "texto": linea[:400], "trozo": m.group(0)[:200]})
                    total += 1
                    if total >= limite:
                        truncado = True
                        break
                if truncado:
                    break
            if coincidencias:
                resultados.append({"path": ruta, "rel": rel, "coincidencias": coincidencias})
            if truncado:
                break
        return {"resultados": resultados, "total": total, "archivos": len(resultados),
                "revisados": revisados, "truncado": truncado}

    def reemplazar(self, consulta: str, reemplazo: str, regex: bool = False,
                   mayusculas: bool = False, palabra: bool = False, incluir: str = "",
                   excluir: str = "", solo: Optional[List[str]] = None) -> Dict[str, Any]:
        """ Reemplaza en disco. `solo` limita a esas rutas (las que el usuario dejó
        marcadas en los resultados, sin las que tienen cambios sin guardar). """
        expr = self._expresion(consulta, regex, mayusculas, palabra)
        permitidas = {self.fm.resolve(p) for p in solo} if solo is not None else None
        cambiados, total = [], 0
        for ruta, rel, texto in self._archivos_texto(incluir, excluir):
            if permitidas is not None and ruta not in permitidas:
                continue
            try:
                # Sin regex, el reemplazo es literal: "\\1" o "\\n" no se interpretan
                nuevo, n = expr.subn(reemplazo if regex else (lambda m: reemplazo), texto)
            except (re.error, IndexError) as e:
                raise ErrorIDE(f"Reemplazo no válido: {e}")
            if n:
                tmp = ruta + ".prig-tmp"
                with open(tmp, "w", encoding="utf-8", newline="") as f:
                    f.write(nuevo)
                shutil.copymode(ruta, tmp)
                os.replace(tmp, ruta)
                cambiados.append({"path": ruta, "rel": rel, "reemplazos": n})
                total += n
        return {"archivos": cambiados, "total": total}

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

    # ------------------------------------------------------------ recientes
    def _config(self) -> Dict[str, Any]:
        try:
            with open(self.fm.config_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def recientes(self) -> List[Dict[str, Any]]:
        vistas = self._config().get("recent_workspaces") or []
        salida = []
        for ruta in vistas:
            if os.path.isdir(ruta):
                salida.append({"path": ruta, "name": os.path.basename(ruta) or ruta,
                               "actual": ruta == self.fm.base_dir})
        return salida

    def anotar_reciente(self, ruta: str):
        config = self._config()
        lista = [r for r in (config.get("recent_workspaces") or []) if r != ruta]
        config["recent_workspaces"] = [ruta] + lista[:MAX_RECIENTES - 1]
        config["last_workspace"] = config.get("last_workspace") or ruta
        try:
            tmp = self.fm.config_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(config, f)
            os.replace(tmp, self.fm.config_path)
        except OSError:
            pass

    def olvidar_recientes(self):
        config = self._config()
        config["recent_workspaces"] = []
        with open(self.fm.config_path, "w", encoding="utf-8") as f:
            json.dump(config, f)

    # ------------------------------------------------------------ sistema
    def mostrar_en_sistema(self, ruta: str) -> Dict[str, Any]:
        destino = self.fm.resolve(ruta)
        if not os.path.exists(destino):
            raise ErrorIDE(f"No existe: {ruta}")
        carpeta = destino if os.path.isdir(destino) else os.path.dirname(destino)
        if sys.platform.startswith("linux"):
            # Nautilus y similares seleccionan el archivo con D-Bus; si no, se abre la carpeta
            if os.path.isfile(destino) and shutil.which("dbus-send"):
                r = subprocess.run(
                    ["dbus-send", "--session", "--dest=org.freedesktop.FileManager1",
                     "--type=method_call", "/org/freedesktop/FileManager1",
                     "org.freedesktop.FileManager1.ShowItems",
                     f"array:string:file://{destino}", "string:"],
                    capture_output=True, timeout=5)
                if r.returncode == 0:
                    return {"success": True}
            cmd = ["xdg-open", carpeta]
        elif sys.platform == "darwin":
            cmd = ["open", "-R", destino]
        else:
            cmd = ["explorer", "/select,", destino]
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        except FileNotFoundError:
            raise ErrorIDE("No se encontró un explorador de archivos en el sistema.")
        return {"success": True}
