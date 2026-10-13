"""
Calculadora: cuánta memoria ocupará un modelo, dónde irá y a qué velocidad.

Las fórmulas están calibradas contra mediciones reales, no contra hojas de datos.
Sobre una RTX 4050 portátil de 6 GB, con qwen2.5-coder:7b, qwen3:14b y
qwen3:30b-a3b a contextos de 2048, 4096 y 8192:

    memoria total        error medio 0,3 %   (máximo 0,5 %)
    reparto GPU/CPU      exacto a un punto
    velocidad            error medio 11 %    (máximo 24 %)

MEMORIA. Total = pesos + caché KV + búfer de cómputo. El búfer resultó casi
constante: −0,15 GB cuando el modelo cabe entero (parte del vocabulario se queda en
RAM) y +0,25 GB cuando se reparte entre GPU y CPU.

HASTA DÓNDE LLENA OLLAMA LA GPU. Nunca pasó de 4,85 GB en una tarjeta de 6,1. Forzar
más capas a mano no aceleró nada (14B con 22 capas: 5,9 tok/s, igual que con las
automáticas) y con 24 reventó por falta de memoria. Por eso esta calculadora predice
el reparto automático de Ollama en lugar de pelearse con él.

VELOCIDAD. Generar un token obliga a leer los parámetros activos una vez. Lo que va
en GPU se lee a la velocidad de la VRAM y lo que va en RAM a la de la RAM:

    t_token = fracción_gpu × activos / ancho_gpu  +  (1 − fracción_gpu) × activos / ancho_cpu

En un MoE los activos son una fracción pequeña del total (3,4 B de 30,5 B en
qwen3:30b-a3b), y por eso va a 22-28 tok/s con solo el 25 % en GPU mientras un 14B
denso con el 48 % va a 6.
Todo está en Rust (backend-rust/crates/prig-recursos, calculadora.rs): los mismos números y textos.
"""

from typing import Any, Dict, List, Optional


def _rs():
    from nativo_rust import rust
    return rust().calculadora


_c = _rs()
GB = _c.GB
# Valores medidos en la máquina de referencia. Solo se usan hasta que la calibración de la máquina del usuario los
# sustituye por los suyos.
OVERHEAD_ENTERO = _c.OVERHEAD_ENTERO
OVERHEAD_PARCIAL = _c.OVERHEAD_PARCIAL
MARGEN_RAM = _c.MARGEN_RAM              # lo que se deja al sistema antes de hablar de swap
FACTOR_BANCO_RAM = _c.FACTOR_BANCO_RAM  # medida en Python puro → ancho efectivo en inferencia
ANCHO_GPU = _c.ANCHO_GPU                # GB/s nominales de GPUs conocidas
EFICIENCIA_GPU = _c.EFICIENCIA_GPU      # el efectivo en inferencia es un 93 % del nominal
LATENCIA_CAPA_S = _c.LATENCIA_CAPA_S    # coste fijo por capa y token
GANANCIA_RANURA = _c.GANANCIA_RANURA    # dos peticiones simultáneas rinden 1,32 veces lo que una
VEREDICTOS = _c.VEREDICTOS

# Lo que la calculadora necesita saber de la máquina, ya destilado: Maquina(radiografia, calibracion=None).
# Cada valor recuerda de dónde sale ("medido" o "previo") para poder decir al usuario cuánto fiarse.
Maquina = _c.Maquina


def servidor_efectivo(entorno: Dict[str, str]) -> Dict[str, Any]:
    """ Lo que el servidor aplica de verdad, rellenando los valores por defecto """
    return _c.servidor_efectivo(entorno)


def penalizacion_contexto(ctx: int) -> float:
    """ La atención cuesta más cuanto más contexto: ~3,5 % cada vez que se dobla """
    return _c.penalizacion_contexto(ctx)


def estimar(ficha: Dict[str, Any], maq: Maquina, ctx: int,
            paralelo: int = 1, kv: str = "f16") -> Dict[str, Any]:
    """ Memoria, reparto GPU/RAM y velocidad de una configuración concreta """
    return _c.estimar(ficha, maq, ctx, paralelo, kv)


def recomendar(ficha: Dict[str, Any], maq: Maquina, nombre_perfil: str,
               tirador: str = "equilibrado") -> Dict[str, Any]:
    """ Veredicto, opciones, motivo, alternativas y lo que se ganaría cambiando el servidor """
    return _c.recomendar(ficha, maq, nombre_perfil, tirador)


def rendimiento(e: Dict[str, Any]) -> float:
    """ Tokens por segundo sumando todas las ranuras """
    return _c.rendimiento(e)


def calidad_esperada(ficha: Dict[str, Any]) -> float:
    """ Una aproximación a "cuánto sabe" un modelo, para ordenar candidatos """
    return _c.calidad_esperada(ficha)


def elegir_modelo(fichas: List[Dict[str, Any]], maq: Maquina, nombre_perfil: str,
                  tirador: str = "equilibrado",
                  medidas: Optional[Dict[str, Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """ Modelos instalados ordenados de mejor a peor para este uso """
    return _c.elegir_modelo(fichas, maq, nombre_perfil, tirador, medidas)
