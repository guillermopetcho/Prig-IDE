"""
Motor Nativo de Monitoreo y Análisis de Audio del Sistema para Prig IDE (Linux / PulseAudio / PipeWire).
Permite listar aplicaciones y pestañas abiertas que reproducen audio (Spotify, Chrome, Firefox, YouTube, VLC, etc.)
y analizar el espectro de frecuencias en tiempo real para modular los efectos visuales.

La captura (parec) y la FFT van en Rust (backend-rust/crates/prig-recursos, audio.rs), en un hilo que no toca
Python: en Python ese hilo se quedaba el GIL ~50 veces por segundo y frenaba a los demás. Las cuentas son las
mismas y el espectro sale idéntico.
"""

from typing import Any, Dict, List


def _rs():
    from nativo_rust import rust
    return rust().audio


class AudioMonitorNativo:
    def __init__(self):
        self._n = _rs().MonitorAudio()

    @property
    def datos_actuales(self) -> Dict[str, Any]:
        """ {activo, fuente, bass, mids, treble, energy, rms, spectrum (32 bandas)} """
        return self._n.datos_actuales

    def listar_aplicaciones_audio(self) -> List[Dict[str, Any]]:
        """
        Lista todas las aplicaciones, reproductores y pestañas de navegador que están
        reproduciendo sonido actualmente en el sistema operativo mediante PulseAudio/PipeWire.
        """
        return self._n.listar_aplicaciones_audio()

    def seleccionar_fuente(self, fuente_id: str):
        """ Cambia la fuente de audio objetivo (ID de sink-input o 'sistema_global'). """
        self._n.seleccionar_fuente(fuente_id)

    def incrementar_suscriptor(self):
        self._n.incrementar_suscriptor()

    def decrementar_suscriptor(self):
        self._n.decrementar_suscriptor()

    def registrar_suscriptor(self, q=None):
        self.incrementar_suscriptor()

    def desregistrar_suscriptor(self, q=None):
        self.decrementar_suscriptor()


# Instancia singleton global para el backend
audio_monitor = AudioMonitorNativo()
