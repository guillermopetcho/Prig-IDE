"""
Calibración: medir de verdad en la máquina del usuario.

La calculadora parte de valores previos (ancho de banda de GPUs conocidas, reserva
típica de Ollama). Son buenos para ordenar, no para prometer. Una prueba corta con
un modelo real da tres números que sustituyen a los previos:

  · presupuesto de GPU: cuánto llena Ollama la tarjeta cuando un modelo no cabe.
  · ancho de GPU: se despeja de la velocidad de un modelo que cabe entero.
  · ancho de CPU: se despeja de un modelo repartido, conocido ya el de GPU.

Cada prueba es además un CANARIO de extracción: se pide un JSON con citas literales
de un texto y se comprueba que las citas existen. Es lo que se estropeó al cuantizar
la caché, y no se ve mirando solo la velocidad.

Falta de memoria: si Ollama revienta al cargar, se reintenta bajando primero el
contexto y después las capas en GPU. Se guarda la primera configuración que funciona.

Calor: antes de cada prueba se espera a que la GPU baje de temperatura, cada prueba
genera poco y el modelo se descarga al terminar. Solo una calibración a la vez.
Las decisiones, el canario, la GPU, Ollama y la prueba están en Rust (backend-rust/crates/prig-recursos,
calibracion.rs). Aquí quedan las piezas de Python que la prueba usa (el hilo que mide la GPU, el gobernador, el
motor que explica los errores) y el encadenado de calibrar y probar una recomendación.
"""

import threading
import time
from typing import Any, Callable, Dict, List, Optional

from .calculadora import Maquina, estimar, recomendar
from . import termico

OLLAMA = "http://localhost:11434"


def _rs():
    from nativo_rust import rust
    return rust().calibracion


# Temperaturas: las del gobernador térmico (límite de la GPU, 60 °C por defecto).
# Antes de cada prueba se espera a la de reanudar; si durante la prueba se llega al
# límite, se corta, se enfría y se repite una vez.
ESPERA_MAX_S = _rs().ESPERA_MAX_S
MAX_INTENTOS = _rs().MAX_INTENTOS
# Por debajo de esto, la calidad medida no se usa para ordenar modelos
CITAS_MINIMAS = _rs().CITAS_MINIMAS
TEXTO_CANARIO = _rs().TEXTO_CANARIO
PROMPT_CANARIO = _rs().PROMPT_CANARIO

EN_CURSO = threading.Lock()

Evento = Callable[[Dict[str, Any]], None]


class Cancelado(Exception):
    pass


class _PorCalor(Exception):
    pass


# ===========================================================================
# Canario
# ===========================================================================

def puntuar_canario(respuesta: str) -> Dict[str, Any]:
    """ 0..1: fracción de citas que están de verdad en el texto.

    Las citas se sacan también de un JSON cortado: la prueba limita los tokens para
    no calentar la GPU, y en la primera versión el tope cortaba el JSON antes de
    cerrar ninguna cita, así que TODOS los modelos puntuaban 0.
    """
    return _rs().puntuar_canario(respuesta)


# ===========================================================================
# Sensores
# ===========================================================================

def estado_gpu() -> Optional[Dict[str, float]]:
    return _rs().estado_gpu()


class Muestreador(threading.Thread):
    """ Pico de VRAM y temperatura mientras dura la prueba """

    def __init__(self, limite: Optional[float] = None):
        super().__init__(daemon=True)
        self.parar = threading.Event()
        self.limite = limite
        self.vram_pico_mb = 0.0
        self.temp_max = 0.0
        self.caliente = False

    def run(self):
        while not self.parar.is_set():
            e = estado_gpu()
            if e:
                self.vram_pico_mb = max(self.vram_pico_mb, e["vram_mb"])
                self.temp_max = max(self.temp_max, e["temp_c"])
                if self.limite is not None and e["temp_c"] >= self.limite:
                    self.caliente = True
            self.parar.wait(0.5)


class _MundoPrueba:
    """ Lo que la prueba (en Rust) pide fuera: cada pieza se busca aquí en el momento, para poder sustituirla """

    def __init__(self, avisar: Evento, cancelar: threading.Event,
                 generar: Optional[Callable[..., dict]] = None,
                 ps: Optional[Callable[[str], Optional[dict]]] = None):
        self._avisar, self._cancelar = avisar, cancelar
        self.muestras: Optional[Muestreador] = None
        self._generar = generar or (lambda cuerpo: _generar_stream(
            cuerpo, lambda: bool(self.muestras and self.muestras.caliente)))
        self._ps = ps or _ps

    def cancelado(self) -> bool:
        return self._cancelar.is_set()

    def cancelar(self):
        return Cancelado()

    def esperar(self, s: float) -> bool:
        return self._cancelar.wait(s)

    def dormir(self, s: float):
        time.sleep(s)

    def ahora(self) -> float:
        return time.time()

    def estado_gpu(self):
        return estado_gpu()

    def reanudar(self) -> float:
        return termico.gobernador().reanudar

    def limite(self) -> float:
        return termico.gobernador().limite

    def avisar(self, evento: Dict[str, Any]):
        self._avisar(evento)

    def muestreo_empezar(self, limite: float):
        self.muestras = Muestreador(limite)
        self.muestras.start()

    def muestreo_terminar(self):
        self.muestras.parar.set()
        self.muestras.join(timeout=2)
        return float(self.muestras.vram_pico_mb), float(self.muestras.temp_max)

    def generar(self, cuerpo: dict):
        try:
            return ("hecho", self._generar(cuerpo))
        except _PorCalor:
            return ("calor", None)
        except Exception as e:
            return ("error", str(e))

    def ps(self, modelo: str):
        return self._ps(modelo)

    def descargar(self, modelo: str):
        descargar(modelo)

    def explicar(self, error: str) -> str:
        try:
            from ai_engine.ai_engine_class import explicar_error_motor
            return explicar_error_motor(error) or error
        except ImportError:
            return error


def esperar_temperatura(avisar: Evento, cancelar: threading.Event,
                        tope: Optional[float] = None, espera_max: float = ESPERA_MAX_S) -> bool:
    return _rs().esperar_temperatura(_MundoPrueba(avisar, cancelar), tope, espera_max)


# ===========================================================================
# Ollama
# ===========================================================================

def _generar_stream(cuerpo: dict, parar: Callable[[], bool], timeout: float = 600) -> dict:
    """ Genera en streaming para poder cortar si la GPU llega al límite.
    Devuelve el último mensaje (el que trae las estadísticas) con la respuesta entera. """
    return _rs().generar_stream(OLLAMA, cuerpo, parar, timeout, _PorCalor)


def _ps(modelo: str) -> Optional[Dict[str, Any]]:
    return _rs().ps(OLLAMA, modelo)


def descargar(modelo: str):
    _rs().descargar(OLLAMA, modelo)


def es_oom(mensaje: str) -> bool:
    return _rs().es_oom(mensaje)


# ===========================================================================
# Una prueba
# ===========================================================================

def probar(ficha: Dict[str, Any], opciones: Dict[str, Any], avisar: Evento = lambda e: None,
           cancelar: Optional[threading.Event] = None, num_predict: int = 200,
           dejar_cargado: bool = False, generar: Optional[Callable[..., dict]] = None,
           ps: Optional[Callable[[str], Optional[dict]]] = None) -> Dict[str, Any]:
    """ Carga el modelo con estas opciones, genera el canario y mide.

    `generar` y `ps` se pueden sustituir (pruebas automáticas sin GPU).
    Si revienta por memoria, reintenta: primero menos contexto, luego menos capas.
    """
    mundo = _MundoPrueba(avisar, cancelar or threading.Event(), generar, ps)
    return _rs().probar(mundo, ficha, opciones, num_predict, dejar_cargado)


def reducir(ficha: Dict[str, Any], opc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """ El siguiente escalón tras una falta de memoria.

    Primero el contexto (hasta 2048): es barato y no cambia la velocidad por token.
    Después las capas en GPU, en saltos de un cuarto: más RAM y menos velocidad,
    pero funciona. Con 0 capas ya no queda nada que quitar a la GPU.
    """
    return _rs().reducir(ficha, opc)


# ===========================================================================
# Deducir los parámetros de la máquina
# ===========================================================================

def deducir(ficha: Dict[str, Any], r: Dict[str, Any], maq: Maquina) -> Dict[str, Any]:
    """ Despeja lo que la prueba permite saber. Devuelve solo lo medido. """
    return _rs().deducir(ficha, r, maq)


def combinar(previa: Optional[Dict[str, Any]], nuevas: List[Dict[str, Any]]) -> Dict[str, Any]:
    """ Mediana de todas las muestras de cada parámetro, las viejas incluidas """
    return _rs().combinar(previa, list(nuevas))


# ===========================================================================
# Calibración completa
# ===========================================================================

def elegir_modelos_prueba(fichas: List[Dict[str, Any]], maq: Maquina) -> List[Dict[str, Any]]:
    """ Dos modelos instalados que den información distinta.

    Uno que quepa entero (mide la GPU) y uno que se reparta (mide el presupuesto y
    la RAM). De cada clase el más pequeño que sirva: carga antes y calienta menos.
    Sin GPU, uno pequeño basta.
    """
    return _rs().elegir_modelos_prueba(list(fichas), maq)


def calibrar(fichas: List[Dict[str, Any]], maq: Maquina, avisar: Evento = lambda e: None,
             cancelar: Optional[threading.Event] = None,
             previa: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not EN_CURSO.acquire(blocking=False):
        raise RuntimeError("Ya hay una calibración en marcha.")
    cancelar = cancelar or threading.Event()
    try:
        elegidos = elegir_modelos_prueba(fichas, maq)
        if not elegidos:
            return {"ok": False, "error": "No hay ningún modelo instalado con el que medir."}
        avisar({"tipo": "plan", "modelos": [f["nombre"] for f in elegidos],
                "mensaje": "Voy a medir con " + " y ".join(f["nombre"] for f in elegidos)
                           + ". Cada prueba dura unos segundos y el modelo se descarga al "
                             "terminar."})
        pruebas, deducidos = [], []
        for f in elegidos:
            r = probar(f, {"num_ctx": 4096}, avisar, cancelar)
            prevista = estimar(f, maq, r["opciones"].get("num_ctx", 4096))
            r["prevision"] = {k: prevista[k] for k in ("tok_s", "total_gb", "fraccion_gpu")}
            pruebas.append(r)
            d = deducir(f, r, maq)
            if d:
                deducidos.append(d)
                # Lo recién medido de la GPU sirve para despejar la CPU en la siguiente
                maq = Maquina(maq.radiografia, combinar(previa, deducidos))
            time.sleep(3)
        if not deducidos:
            return {"ok": False, "pruebas": pruebas,
                    "error": next((p.get("error") for p in pruebas if p.get("error")),
                                  "Las pruebas no dieron medidas utilizables.")}
        valores = combinar(previa, deducidos)
        avisar({"tipo": "calibrado", "valores": {k: v for k, v in valores.items()
                                                 if k != "muestras"}})
        return {"ok": True, "valores": valores, "pruebas": pruebas}
    finally:
        EN_CURSO.release()


def probar_recomendacion(ficha: Dict[str, Any], maq: Maquina, perfil: str, tirador: str,
                         avisar: Evento = lambda e: None,
                         cancelar: Optional[threading.Event] = None) -> Dict[str, Any]:
    """ El botón "Probar": la recomendación con la máquina, y la comparación """
    if not EN_CURSO.acquire(blocking=False):
        raise RuntimeError("Ya hay una prueba o calibración en marcha.")
    try:
        rec = recomendar(ficha, maq, perfil, tirador)
        if rec["veredicto"] == "no_viable":
            return {"ok": False, "error": rec["motivo"], "recomendacion": rec}
        r = probar(ficha, rec["opciones"], avisar, cancelar)
        r["recomendacion"] = rec
        if r.get("ok"):
            prev = rec["estimacion"]
            r["desvio"] = {
                "tok_s_pct": round(100 * (r["tok_s"] - prev["tok_s"]) / max(prev["tok_s"], 0.1)),
                "total_gb_pct": (round(100 * (r["total_gb"] - prev["total_gb"])
                                       / max(prev["total_gb"], 0.01))
                                 if r.get("total_gb") else None),
            }
            r["deducido"] = deducir(ficha, r, maq)
            if r["opciones"] != {k: v for k, v in rec["opciones"].items()
                                 if k in ("num_ctx", "num_gpu")}:
                r["aviso"] = ("La recomendación no cupo tal cual: funcionó con "
                              f"{r['opciones']}. Se usará esto.")
        return r
    finally:
        EN_CURSO.release()
