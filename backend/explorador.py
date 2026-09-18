"""
Explorador de carpetas para elegir libros.

Escribir la ruta a mano es la peor forma de elegir un archivo: hay que acordarse de
dónde está, teclearlo bien y, si te equivocas, el error llega después. Esto lista
carpetas y libros para que se elija viéndolos.

Sobre el alcance, que aquí importa: este módulo SOLO LISTA. Devuelve nombres,
tamaños y fechas; nunca el contenido de un archivo. Leer un libro sigue pasando por
el sondeo, que es una acción explícita sobre un archivo concreto que el usuario ha
señalado. El confinamiento de lectura y escritura de `file_manager` no se toca.

Aun así la navegación es más amplia que ese confinamiento —tiene que serlo, porque
los libros suelen estar en Descargas o en Documentos, no dentro del espacio de
trabajo— así que se limita al directorio del usuario y se excluye todo lo oculto.
"""

import os
import time
from typing import Any, Dict, List, Optional

EXTENSIONES = {
    ".pdf": "PDF",
    ".epub": "EPUB",
    ".djvu": "DjVu",
    ".md": "Markdown",
    ".txt": "Texto",
    ".rst": "reStructuredText",
    ".ipynb": "Cuaderno",
    ".tex": "LaTeX",
}

# Carpetas que nunca interesan y solo hacen ruido al navegar
IGNORADAS = {
    "node_modules", "__pycache__", "site-packages", ".git", ".cache",
    "snap", "venv", ".venv", "env", "AppData", "Library", "Trash",
    ".local", ".config", ".mozilla", ".steam", "Papelera",
}

# Dónde suele haber libros. Se ofrecen como atajos al abrir el explorador.
ATAJOS = [
    ("Biblioteca de Prig", "~/.prig_books"),
    ("Descargas", "~/Descargas"),
    ("Downloads", "~/Downloads"),
    ("Documentos", "~/Documentos"),
    ("Documents", "~/Documents"),
    ("Escritorio", "~/Escritorio"),
    ("Desktop", "~/Desktop"),
    ("Carpeta personal", "~"),
]


class Explorador:
    def __init__(self, workspace: Optional[str] = None):
        self.workspace = os.path.abspath(workspace) if workspace else None
        self.raiz = os.path.abspath(os.path.expanduser("~"))

    # ------------------------------------------------------------------

    def permitida(self, ruta: str) -> bool:
        """ Solo dentro del directorio del usuario, o del espacio de trabajo.

        Se comprueba sobre la ruta REAL (resuelve enlaces simbólicos): sin eso, un
        enlace dentro de la carpeta personal apuntando a / dejaría navegar el disco
        entero.
        """
        real = os.path.realpath(ruta)
        permitidas = [self.raiz] + ([self.workspace] if self.workspace else [])
        return any(real == p or real.startswith(p + os.sep)
                   for p in (os.path.realpath(x) for x in permitidas))

    def atajos(self) -> List[Dict[str, str]]:
        salida = []
        for nombre, ruta in ATAJOS:
            completa = os.path.abspath(os.path.expanduser(ruta))
            if os.path.isdir(completa) and not any(s["ruta"] == completa for s in salida):
                salida.append({"nombre": nombre, "ruta": completa})
        if self.workspace and os.path.isdir(self.workspace):
            salida.insert(0, {"nombre": "Espacio de trabajo", "ruta": self.workspace})
        return salida

    # ------------------------------------------------------------------

    def listar(self, ruta: Optional[str] = None, recursivo: bool = False
               ) -> Dict[str, Any]:
        """ Carpetas y libros de una ruta. Nunca el contenido de un archivo. """
        ruta = os.path.abspath(os.path.expanduser(ruta or "~"))
        if not self.permitida(ruta):
            raise PermissionError(
                f"Solo se puede navegar dentro de tu carpeta personal. "
                f"'{ruta}' queda fuera.")
        if not os.path.isdir(ruta):
            raise NotADirectoryError(f"No es una carpeta: {ruta}")

        carpetas, libros = [], []
        try:
            entradas = sorted(os.scandir(ruta), key=lambda e: e.name.lower())
        except PermissionError:
            raise PermissionError(f"Sin permiso para leer {ruta}")

        for e in entradas:
            if e.name.startswith(".") or e.name in IGNORADAS:
                continue
            try:
                if e.is_dir(follow_symlinks=False):
                    carpetas.append({
                        "nombre": e.name, "ruta": e.path,
                        # Cuántos libros hay dentro, para no entrar a ciegas. Solo
                        # el primer nivel: recorrer el árbol entero al listar haría
                        # lenta cada navegación.
                        "libros_dentro": self._contar(e.path),
                    })
                elif e.is_file(follow_symlinks=False):
                    ext = os.path.splitext(e.name)[1].lower()
                    if ext not in EXTENSIONES:
                        continue
                    st = e.stat()
                    libros.append({
                        "nombre": e.name, "ruta": e.path, "tipo": EXTENSIONES[ext],
                        "extension": ext,
                        "mb": round(st.st_size / (1024 * 1024), 2),
                        "modificado": time.strftime("%Y-%m-%d", time.localtime(st.st_mtime)),
                    })
            except OSError:
                continue

        if recursivo:
            libros += self._buscar_hondo(ruta, ya=len(libros))

        padre = os.path.dirname(ruta)
        return {
            "ruta": ruta,
            "nombre": os.path.basename(ruta) or ruta,
            "padre": padre if self.permitida(padre) and padre != ruta else None,
            "migas": self._migas(ruta),
            "carpetas": carpetas,
            "libros": libros,
            "total_libros": len(libros),
        }

    def _contar(self, carpeta: str, tope: int = 200) -> int:
        n = 0
        try:
            for e in os.scandir(carpeta):
                if e.name.startswith("."):
                    continue
                if e.is_file(follow_symlinks=False) and \
                        os.path.splitext(e.name)[1].lower() in EXTENSIONES:
                    n += 1
                    if n >= tope:
                        break
        except OSError:
            return 0
        return n

    def _buscar_hondo(self, ruta: str, ya: int, tope: int = 300) -> List[Dict[str, Any]]:
        """ Los libros de las subcarpetas, para carpetas organizadas por materia """
        salida = []
        for raiz, dirs, ficheros in os.walk(ruta):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in IGNORADAS]
            if raiz == ruta:
                continue
            for nombre in sorted(ficheros):
                ext = os.path.splitext(nombre)[1].lower()
                if ext not in EXTENSIONES:
                    continue
                completa = os.path.join(raiz, nombre)
                try:
                    st = os.stat(completa)
                except OSError:
                    continue
                salida.append({
                    "nombre": nombre, "ruta": completa, "tipo": EXTENSIONES[ext],
                    "extension": ext,
                    "mb": round(st.st_size / (1024 * 1024), 2),
                    "modificado": time.strftime("%Y-%m-%d", time.localtime(st.st_mtime)),
                    "subcarpeta": os.path.relpath(raiz, ruta),
                })
                if ya + len(salida) >= tope:
                    return salida
        return salida

    def _migas(self, ruta: str) -> List[Dict[str, str]]:
        """ El camino desde la carpeta personal, para poder volver atrás """
        migas, actual = [], ruta
        while self.permitida(actual):
            migas.insert(0, {"nombre": os.path.basename(actual) or actual, "ruta": actual})
            padre = os.path.dirname(actual)
            if padre == actual:
                break
            actual = padre
        return migas

    # ------------------------------------------------------------------

    def buscar(self, texto: str, desde: Optional[str] = None,
               tope: int = 120) -> List[Dict[str, Any]]:
        """ Busca un libro por su nombre en todo el árbol.

        Para cuando sabes cómo se llama pero no dónde lo dejaste, que es lo normal
        con una carpeta de descargas de varios años.
        """
        desde = os.path.abspath(os.path.expanduser(desde or "~"))
        if not self.permitida(desde):
            raise PermissionError("Esa carpeta queda fuera de tu carpeta personal")
        agujas = [t for t in texto.lower().split() if t]
        if not agujas:
            return []

        salida = []
        for raiz, dirs, ficheros in os.walk(desde):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in IGNORADAS]
            for nombre in ficheros:
                ext = os.path.splitext(nombre)[1].lower()
                if ext not in EXTENSIONES:
                    continue
                # Todas las palabras, en cualquier orden: "python machine" encuentra
                # "Machine Learning con Python"
                bajo = nombre.lower()
                if not all(a in bajo for a in agujas):
                    continue
                completa = os.path.join(raiz, nombre)
                try:
                    st = os.stat(completa)
                except OSError:
                    continue
                salida.append({
                    "nombre": nombre, "ruta": completa, "tipo": EXTENSIONES[ext],
                    "extension": ext,
                    "mb": round(st.st_size / (1024 * 1024), 2),
                    "modificado": time.strftime("%Y-%m-%d", time.localtime(st.st_mtime)),
                    "carpeta": os.path.dirname(completa),
                })
                if len(salida) >= tope:
                    return salida
        return salida
