"""
Modo suave: que los modelos trabajen de forma continua y gradual, sin picos de calor.

Medido en el portátil del usuario (i5-13420H + RTX 4050 6 GB, qwen2.5-coder:7b):

  GPU. En cuanto empieza a generar pasa de 7 W a 40 W (su tope) y sube unos 7 °C en un
  segundo; sin parar se asienta en 64,5 °C. El límite de potencia (nvidia-smi -pl) y
  los relojes necesitan permisos de administrador, así que Prig no puede bajarlos. Lo
  que sí puede es DOSIFICAR el trabajo: generar un tramo corto, pausar y seguir donde
  quedó (Ollama lo retoma igual, releyendo lo ya escrito en 7 ms). Con tramos de 0,25 s
  y pausas iguales la media baja de 40 a 32 W y la temperatura estable de 64,5 a 60 °C.

  Aquí la pausa no es fija: se calcula como un termostato proporcional. Lejos de la
  temperatura objetivo trabaja a pleno; al acercarse, las pausas se alargan poco a poco
  y la temperatura se queda cerca del objetivo en vez de subir y bajar en diente de
  sierra (que es lo que hace el corte de emergencia del gobernador al tocar el límite).
  Además hay ARRANQUE GRADUAL: tras un rato sin trabajar, la primera parte de cada
  respuesta va a ritmo reducido y sube hasta el 100 % a lo largo de la rampa, para que
  la máquina (y sus ventiladores) no pasen de golpe de reposo a tope.

  CPU. Con el modelo entero en la GPU, un hilo del motor espera a la GPU sin parar: la
  CPU saltaba de 43 a 80-92 °C. Fijar el proceso del modelo (llama-server) a los núcleos
  de EFICIENCIA la deja en 69-72 °C a la misma velocidad (38 tok/s). No hace falta ser
  administrador: el proceso es del propio usuario. Solo se hace si el modelo cabe entero
  en la GPU; si una parte va en la CPU, esos núcleos lo frenarían y se dejan todos.
  (Quitar el «sondeo» de llama.cpp con LLAMA_ARG_POLL=0 se probó y no cambia nada.)
Todo está en Rust (backend-rust/crates/prig-recursos, ritmo.rs). Aquí quedan las fachadas: el reloj es time.time()
y los núcleos E salen de nucleos_eficientes() de este módulo, para poder sustituirlos en las pruebas.
"""

from typing import Any, Dict, List


def _rs():
    from nativo_rust import rust
    return rust().ritmo


AJUSTES_POR_DEFECTO = _rs().AJUSTES_POR_DEFECTO
BANDA_C = _rs().BANDA_C                  # por debajo de objetivo − BANDA trabaja a pleno
REPOSO_S = _rs().REPOSO_S                # tras este tiempo sin generar, la rampa vuelve a empezar
PAUSA_MAXIMA_S = _rs().PAUSA_MAXIMA_S
# El servidor del motor MoE (ai_engine/motor_moe.py) usa el mismo GGUF que el modelo de Ollama; como no aparece en
# /api/ps, sin esto se le ponían todos los núcleos y se deshacía su fijación a los P (medido en Prig: 10–12 tok/s en
# lugar de 45–57).
MOTOR_MOE = _rs().MOTOR_MOE


class Ritmo(_rs().Ritmo):
    """ Cuánto trabajar y cuánto descansar en cada momento: Ritmo(ajustes=None, guardar=None), con fijar, activo,
    ajustes, ultimo, marcar, fraccion, pausa y estado """

    def estado(self, temp=None) -> Dict[str, Any]:
        return super().estado(temp, lambda: nucleos_eficientes())


# ===========================================================================
# Núcleos de eficiencia
# ===========================================================================

def _leer_lista_cpus(texto: str) -> List[int]:
    return _rs().leer_lista_cpus(texto or "")


def nucleos_eficientes() -> List[int]:
    """ Los E-cores de los Intel híbridos (12.ª generación en adelante). Vacío si no hay. """
    return _rs().nucleos_eficientes()


class FijadorCPU:
    """ Pone el motor del modelo (llama-server) en los núcleos de eficiencia si el modelo
    está entero en la GPU, y lo devuelve a todos si no. Solo toca procesos del usuario.

    `sistema`: para las pruebas, un objeto con procesos(), hilos(pid), fijar(pid, núcleos), afinidad_propia(),
    uid() y pids(); sin él, el sistema de verdad (/proc y sched_setaffinity, desde Rust). """

    def __init__(self, url_ollama: str = "http://localhost:11434", sistema=None):
        self.url = url_ollama
        self._n = _rs().FijadorCPU(url_ollama)
        # El modo frío (recursos/frio.py) quiere también los modelos en RAM en los núcleos E
        self.ram_en_eficientes = lambda: False
        self._sistema = sistema

    def _nucleos(self) -> List[int]:
        return nucleos_eficientes()

    def _modelos_en_gpu(self) -> Dict[str, bool]:
        """ blob de pesos → True si el modelo está entero en la VRAM """
        return self._n.modelos_en_gpu()

    def aplicar(self, forzar: bool = False) -> Dict[str, Any]:
        return self._n.aplicar(self, forzar)

    @staticmethod
    def fijar_proceso(pid: int, nucleos) -> bool:
        """ El proceso y todos sus hilos a esos núcleos """
        return _rs().fijar_proceso(pid, list(nucleos))

    def soltar(self):
        """ Devuelve todos los núcleos a los procesos que se habían fijado """
        self._n.soltar()
