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
inicio.rs). Juntar los bloques (`resumen`) sigue aquí: las fuentes son funciones de Python que pone app.py.
"""

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional


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


# ===========================================================================
# Todo junto
# ===========================================================================

def _bloque(fn: Callable[[], Any], errores: Dict[str, str], nombre: str, vacio: Any = None) -> Any:
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 - un bloque roto no puede tirar la pantalla entera
        errores[nombre] = str(e)[:300]
        return vacio


def resumen(fuentes: Dict[str, Callable[[], Any]]) -> Dict[str, Any]:
    """ `fuentes` son funciones sin argumentos (las pone app.py con sus objetos) """
    errores: Dict[str, str] = {}
    obtener = lambda nombre, vacio=None: _bloque(fuentes[nombre], errores, nombre, vacio) if nombre in fuentes else vacio  # noqa: E731
    prog = obtener("progreso", {}) or {}
    historial = obtener("historial", []) or []
    lecturas = obtener("lecturas", []) or []
    guardado = obtener("colecciones_recientes", []) or []
    descargas = obtener("descargas", []) or []
    ejercicios = obtener("ejercicios", []) or []
    return {
        "perfil": perfil(),
        "hora": datetime.now().hour,
        "progreso": {k: prog.get(k) for k in ("desafios", "actividades", "racha", "conceptos", "fuertes", "flojos", "siguientes", "rutas")},
        "semana": semana(prog.get("actividad") or {}),
        "actividad": actividad(prog, historial, lecturas, guardado, descargas, ejercicios),
        "modelos": obtener("modelos", []),
        "cargados": obtener("cargados", []),
        "modelo_tutor": obtener("modelo_tutor"),
        "gemini": obtener("gemini"),
        "sistema": obtener("sistema"),
        "temperaturas": obtener("temperaturas"),
        "proyecto": obtener("proyecto"),
        "recientes": obtener("recientes", []),
        "kaggle": {"lecturas": lecturas[:4], "colecciones": (obtener("colecciones", []) or [])[:6],
                   "recientes": guardado, "cuenta": obtener("kaggle_cuenta")},
        "errores": errores,
        "generado": datetime.now().isoformat(timespec="seconds"),
    }
