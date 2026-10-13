"""
El motor del banco del proyecto: el módulo de Rust `prig_banco`, compilado desde ~/prig-memoria.

Indexa, analiza el código, resuelve el grafo, busca, arma el mapa y el paquete de cada pregunta, guarda la memoria,
parte el proyecto en unidades y responde las consultas de la consola. Reemplazó al motor de Python, que hacía lo
mismo sobre el mismo SQLite: mismas tablas, mismos ids, mismos textos para el modelo (comparado fila por fila y
carácter por carácter; docs/plan-banco-rust.md). El motor de Python quedó congelado en ~/prig-memoria/referencia
solo para comparar.

Instalación (en el .venv de Prig):
    cd ~/prig-memoria/crates/banco-py && VIRTUAL_ENV=~/Prig/.venv maturin develop --release
"""

from typing import Any

INTERFAZ = 1          # la versión de la interfaz de prig_banco que entiende Prig

_modulo: Any = None


def rust():
    """ El módulo prig_banco. ImportError si no está instalado o su interfaz no es la que espera Prig. """
    global _modulo
    if _modulo is None:
        try:
            import prig_banco
        except ImportError as e:
            raise ImportError("Falta el motor del banco (prig_banco). Compílalo e instálalo en el .venv de Prig: "
                              "cd ~/prig-memoria/crates/banco-py && VIRTUAL_ENV=~/Prig/.venv maturin develop --release") from e
        interfaz = getattr(prig_banco, "INTERFAZ", None)
        if interfaz != INTERFAZ:
            raise ImportError(f"prig_banco tiene la interfaz {interfaz} y Prig espera la {INTERFAZ}: recompila ~/prig-memoria")
        _modulo = prig_banco
    return _modulo


def consulta(conexion, raiz: str) -> Any:
    """ La consola sobre la misma base que `conexion`, que tiene que ser la de un banco en disco """
    fila = conexion.execute("PRAGMA database_list").fetchone()
    ruta = fila[2] if fila else ""
    if not ruta:
        raise ValueError("La consola del banco necesita una conexión al archivo del banco (no a una base en memoria)")
    return rust().Consulta(ruta, raiz)
