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

Todo está en Rust (backend-rust/crates/prig-plataforma, explorador.rs). La carpeta personal y el espacio de trabajo
son atributos de este objeto y llegan a Rust en cada llamada.
"""

import os
from typing import Any, Dict, List, Optional


def _rs():
    from nativo_rust import rust
    return rust().explorador


EXTENSIONES = dict(_rs().EXTENSIONES)

# Carpetas que nunca interesan y solo hacen ruido al navegar
IGNORADAS = set(_rs().IGNORADAS)

# Dónde suele haber libros. Se ofrecen como atajos al abrir el explorador.
ATAJOS = list(_rs().ATAJOS)


class Explorador:
    def __init__(self, workspace: Optional[str] = None):
        self.workspace = os.path.abspath(workspace) if workspace else None
        self.raiz = os.path.abspath(os.path.expanduser("~"))

    def permitida(self, ruta: str) -> bool:
        """ Solo dentro del directorio del usuario, o del espacio de trabajo, sobre la ruta REAL (resuelve
        enlaces simbólicos): sin eso, un enlace dentro de la carpeta personal apuntando a / dejaría navegar el
        disco entero. """
        return _rs().permitida(self.raiz, self.workspace, ruta)

    def atajos(self) -> List[Dict[str, str]]:
        return _rs().atajos(self.raiz, self.workspace)

    def listar(self, ruta: Optional[str] = None, recursivo: bool = False) -> Dict[str, Any]:
        """ Carpetas y libros de una ruta. Nunca el contenido de un archivo. """
        return _rs().listar(self.raiz, self.workspace, ruta, bool(recursivo))

    def buscar(self, texto: str, desde: Optional[str] = None, tope: int = 120) -> List[Dict[str, Any]]:
        """ Busca un libro por su nombre en todo el árbol (todas las palabras, en cualquier orden): para cuando
        sabes cómo se llama pero no dónde lo dejaste. """
        return _rs().buscar(self.raiz, self.workspace, texto, desde, tope)
