"""
Energía de la CPU con permisos de root (opcional): turbo apagado, CPU en ahorro y tope de
potencia sostenida. Complementa al modo frío (recursos/frio.py): cada token cuesta menos calor,
así que a la misma temperatura el modelo va más rápido.

El trabajo de root lo hace SOLO el ayudante `prig-energia` (recursos/nativo/), instalado una vez
como root en /usr/local/libexec/ con su política de polkit. Cada uso pasa por pkexec, que pide la
contraseña de administrador (y la recuerda unos minutos): Prig nunca guarda contraseñas ni corre
como root.

Leer el estado no necesita permisos: todo sale de /sys.

Pruebas: PRIG_ENERGIA_AYUDANTE (el script a ejecutar), PRIG_ENERGIA_SIN_PKEXEC=1 (ejecutarlo
directamente, como usuario) y PRIG_ENERGIA_RAIZ (un /sys falso).
Todo está en Rust (backend-rust/crates/prig-recursos, energia.rs); las rutas del ayudante y de la política se
pasan en cada llamada desde aquí.
"""

import os
from typing import Any, Dict

NATIVO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nativo")
FUENTE_AYUDANTE = os.path.join(NATIVO, "prig-energia")
FUENTE_POLITICA = os.path.join(NATIVO, "org.prig.energia.policy")
AYUDANTE = "/usr/local/libexec/prig-energia"
POLITICA = "/usr/share/polkit-1/actions/org.prig.energia.policy"


def _rs():
    from nativo_rust import rust
    return rust().energia


VATIOS_POR_DEFECTO = _rs().VATIOS_POR_DEFECTO


class ErrorEnergia(Exception):
    pass


def _rutas():
    return (AYUDANTE, POLITICA, FUENTE_AYUDANTE, FUENTE_POLITICA)


def instalacion() -> Dict[str, Any]:
    """ ¿Está el ayudante instalado, es de root y es la versión de este Prig? """
    return _rs().instalacion(_rutas())


def estado() -> Dict[str, Any]:
    """ Turbo, gobernador, preferencia de energía y tope de potencia, sin permisos """
    return _rs().estado(_rutas())


def instalar() -> Dict[str, Any]:
    """ Copia el ayudante y su política como root (pide la contraseña una vez) """
    return _rs().instalar(_rutas(), ErrorEnergia)


def frio(vatios: int = VATIOS_POR_DEFECTO) -> Dict[str, Any]:
    """ Turbo apagado, CPU en ahorro y tope de potencia en `vatios` """
    return _rs().frio(_rutas(), ErrorEnergia, vatios)


def normal() -> Dict[str, Any]:
    """ Lo que había antes de «frio» """
    return _rs().normal(_rutas(), ErrorEnergia)
