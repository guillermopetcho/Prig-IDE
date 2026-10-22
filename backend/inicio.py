"""
Inicio: la pantalla con la que abre Prig.

Reúne en una sola respuesta lo que el usuario necesita para decidir qué hacer: su perfil
(nombre, objetivo, racha, dominio), lo último que hizo en cualquier parte del programa,
qué le conviene hacer ahora, sus modelos (locales y Gemini), el estado de la máquina,
sus proyectos recientes y lo que tiene a medias en Kaggle.

Cada bloque se calcula por separado: si uno falla (Ollama apagado, sin sensores…) llega
vacío con su error y el resto de la pantalla funciona igual.

El perfil editable (nombre, objetivo, nivel, herramientas favoritas, abrir al inicio) se
guarda en ~/.prig_inicio.json (o PRIG_INICIO_ARCHIVO).

El perfil, la línea de actividad y la tira de la semana están en Rust (backend-rust/crates/prig-plataforma,
inicio.rs), y la pantalla entera (`/api/inicio`, cada bloque por separado) la arma el servidor de Rust
(prig-server, routes/inicio.rs).
"""

from typing import Any, Dict, List, Optional


def _rs():
    from nativo_rust import rust
    return rust().inicio


NIVELES = tuple(_rs().NIVELES)
PERFIL_POR_DEFECTO = _rs().por_defecto()


def ruta_perfil() -> str:
    return _rs().ruta_perfil()


def perfil() -> Dict[str, Any]:
    return _rs().perfil()


def guardar_perfil(cambios: Dict[str, Any]) -> Dict[str, Any]:
    return _rs().guardar_perfil(cambios)


def actividad(progreso_resumen: Optional[Dict[str, Any]], historial: List[Dict[str, Any]],
              lecturas: List[Dict[str, Any]], colecciones: List[Dict[str, Any]], descargas: List[Dict[str, Any]],
              ejercicios: List[Dict[str, Any]], n: int = 14) -> List[Dict[str, Any]]:
    """ [{tipo, icono, texto, detalle, fecha, abrir:{…}}] del más reciente al más antiguo """
    return _rs().actividad(historial, lecturas, colecciones, descargas, ejercicios, n)


def semana(actividad_por_dia: Dict[str, int], dias: int = 7) -> List[Dict[str, Any]]:
    """ Los últimos días con su número de acciones, para la tira de la semana """
    return _rs().semana(actividad_por_dia, dias)
