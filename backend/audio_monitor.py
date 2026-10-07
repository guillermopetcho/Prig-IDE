"""
Motor Nativo de Monitoreo y Análisis de Audio del Sistema para Prig IDE (Linux / PulseAudio / PipeWire).
Permite listar aplicaciones y pestañas abiertas que reproducen audio (Spotify, Chrome, Firefox, YouTube, VLC, etc.)
y analizar el espectro de frecuencias en tiempo real para modular los efectos visuales.
"""

import subprocess
import threading
import time
import struct
import math
import re
import os
import asyncio
from typing import List, Dict, Any, Optional

class AudioMonitorNativo:
    def __init__(self):
        self._proceso = None
        self._hilo = None
        self._corriendo = False
        self._fuente_actual = "sistema_global"  # 'sistema_global' o id de sink-input
        self._conteo_suscriptores = 0
        self._lock = threading.Lock()

        # Datos en tiempo real
        self.datos_actuales = {
            "activo": False,
            "fuente": "sistema_global",
            "bass": 0.0,
            "mids": 0.0,
            "treble": 0.0,
            "energy": 0.0,
            "rms": 0.0,
            "spectrum": [0.0] * 32
        }

        # Configuración FFT (512 muestras a 16000 Hz = 32ms de ventana, ~31.25 Hz de resolución)
        self.N = 512
        self.RATE = 16000
        self._hann = [0.5 * (1.0 - math.cos(2.0 * math.pi * i / (self.N - 1))) for i in range(self.N)]

        # Precalcular 32 bandas logarítmicas
        self._bandas = []
        min_f, max_f = 30.0, 6000.0
        num_bandas = 32
        puntos_f = [min_f * math.pow(max_f / min_f, i / num_bandas) for i in range(num_bandas + 1)]
        df = self.RATE / self.N
        for i in range(num_bandas):
            k_min = max(1, int(puntos_f[i] / df))
            k_max = min(self.N // 2, int(puntos_f[i + 1] / df) + 1)
            if k_min >= k_max:
                k_max = k_min + 1
            self._bandas.append((k_min, k_max))

    def _fft(self, x):
        """ FFT Cooley-Tukey Radix-2 en Python puro de ultra alta velocidad. """
        n = len(x)
        if n <= 1:
            return x
        even = self._fft(x[0::2])
        odd = self._fft(x[1::2])
        T = [math.e ** (-2j * math.pi * k / n) * odd[k] for k in range(n // 2)]
        return [even[k] + T[k] for k in range(n // 2)] + [even[k] - T[k] for k in range(n // 2)]

    def _get_audio_env(self) -> dict:
        env = dict(os.environ)
        try:
            uid = os.getuid()
            if "XDG_RUNTIME_DIR" not in env or not os.path.exists(env.get("XDG_RUNTIME_DIR", "")):
                if os.path.exists(f"/run/user/{uid}"):
                    env["XDG_RUNTIME_DIR"] = f"/run/user/{uid}"
            if "PULSE_SERVER" not in env:
                if os.path.exists(f"/run/user/{uid}/pulse/native"):
                    env["PULSE_SERVER"] = f"unix:/run/user/{uid}/pulse/native"
        except Exception:
            pass
        env["LC_ALL"] = "C"
        return env

    def listar_aplicaciones_audio(self) -> List[Dict[str, Any]]:
        """
        Lista todas las aplicaciones, reproductores y pestañas de navegador que están
        reproduciendo sonido actualmente en el sistema operativo mediante PulseAudio/PipeWire.
        """
        apps = [
            {
                "id": "sistema_global",
                "app": "Todo el Sistema (Global)",
                "title": "Salida de audio completa de la PC (Todos los programas)",
                "binary": "system",
                "icono": "fa-volume-high",
                "activo": self._fuente_actual == "sistema_global"
            }
        ]

        try:
            env = self._get_audio_env()
            res = subprocess.run(
                ["pactl", "list", "sink-inputs"],
                capture_output=True,
                text=True,
                timeout=3,
                env=env
            )
            if res.returncode == 0 and res.stdout:
                bloques = re.split(r'(?:Sink Input|Entrada del destino|Entrada de sumidero)\s*#', res.stdout, flags=re.IGNORECASE)
                for b in bloques:
                    if not b.strip():
                        continue
                    lineas = b.strip().split('\n')
                    num_id = lineas[0].strip()
                    m_num = re.search(r'^(\d+)', num_id)
                    if not m_num:
                        continue
                    num_id = m_num.group(1)

                    app_name = ""
                    media_name = ""
                    binary = ""

                    m_app = re.search(r'application\.name\s*=\s*\"([^\"]+)\"', b)
                    if m_app:
                        app_name = m_app.group(1)

                    m_media = re.search(r'media\.name\s*=\s*\"([^\"]+)\"', b)
                    if m_media:
                        media_name = m_media.group(1)

                    m_bin = re.search(r'application\.process\.binary\s*=\s*\"([^\"]+)\"', b)
                    if m_bin:
                        binary = m_bin.group(1)

                    # Descartar servicios mudos internos del sistema
                    if (app_name or "").lower() in ["speech-dispatcher-dummy", "sd_dummy"]:
                        continue

                    # Determinar si está pausado
                    m_corked = re.search(r'(?:Corked|Pausado):\s*(\w+)', b, flags=re.IGNORECASE)
                    pausado = False
                    if m_corked:
                        pausado = m_corked.group(1).lower() in ["yes", "sí", "si", "true", "1"]

                    # Determinar ícono amigable
                    icono = "fa-music"
                    app_low = (f"{app_name} {binary} {media_name}").lower()
                    if "firefox" in app_low:
                        icono = "fa-brands fa-firefox-browser"
                    elif "chrome" in app_low or "chromium" in app_low or "brave" in app_low or "edge" in app_low:
                        icono = "fa-brands fa-chrome"
                    elif "spotify" in app_low:
                        icono = "fa-brands fa-spotify"
                    elif "youtube" in app_low:
                        icono = "fa-brands fa-youtube"
                    elif "vlc" in app_low:
                        icono = "fa-video"
                    elif "discord" in app_low:
                        icono = "fa-brands fa-discord"
                    elif "steam" in app_low or "game" in app_low:
                        icono = "fa-gamepad"

                    apps.append({
                        "id": str(num_id),
                        "app": app_name or binary or f"Aplicación #{num_id}",
                        "title": media_name or "Reproducción de Audio",
                        "binary": binary,
                        "icono": icono,
                        "pausado": pausado,
                        "activo": str(self._fuente_actual) == str(num_id)
                    })
        except Exception as e:
            print(f"[AudioMonitorNativo] Error listando aplicaciones con pactl: {e}")

        return apps

    def seleccionar_fuente(self, fuente_id: str):
        """ Cambia la fuente de audio objetivo (ID de sink-input o 'sistema_global'). """
        with self._lock:
            self._fuente_actual = fuente_id

    def incrementar_suscriptor(self):
        with self._lock:
            self._conteo_suscriptores += 1
            if not self._corriendo:
                self._iniciar_captura()

    def decrementar_suscriptor(self):
        with self._lock:
            self._conteo_suscriptores = max(0, self._conteo_suscriptores - 1)
            if self._conteo_suscriptores == 0:
                self._detener_captura()

    def registrar_suscriptor(self, q=None):
        self.incrementar_suscriptor()

    def desregistrar_suscriptor(self, q=None):
        self.decrementar_suscriptor()

    def _iniciar_captura(self):
        if self._corriendo:
            return
        self._corriendo = True
        self._hilo = threading.Thread(target=self._bucle_captura_y_analisis, daemon=True)
        self._hilo.start()

    def _detener_captura(self):
        self._corriendo = False
        if self._proceso:
            try:
                self._proceso.terminate()
            except Exception:
                pass
            self._proceso = None
        with self._lock:
            self.datos_actuales["activo"] = False

    def _bucle_captura_y_analisis(self):
        """ Bucle de alta velocidad en hilo dedicado para lectura y procesamiento FFT de PCM. """
        bytes_por_chunk = self.N * 2  # s16le = 2 bytes por muestra

        def leer_exacto(stream, n_bytes):
            buf = bytearray()
            while len(buf) < n_bytes and self._corriendo:
                parte = stream.read(n_bytes - len(buf))
                if not parte:
                    time.sleep(0.002)
                    continue
                buf.extend(parte)
            return bytes(buf)

        while self._corriendo:
            # Si no hay proceso abierto, iniciarlo conectado al monitor del sistema
            if not self._proceso or self._proceso.poll() is not None:
                cmd = ["parec", "--format=s16le", f"--rate={self.RATE}", "--channels=1", "--latency-msec=20", "-d", "@DEFAULT_SINK@.monitor"]

                try:
                    env = self._get_audio_env()
                    self._proceso = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        bufsize=0,
                        env=env
                    )
                except Exception as e:
                    print(f"[AudioMonitorNativo] Error ejecutando parec: {e}")
                    time.sleep(1.0)
                    continue

            try:
                raw = leer_exacto(self._proceso.stdout, bytes_por_chunk)
                if not raw or len(raw) < bytes_por_chunk:
                    time.sleep(0.01)
                    continue

                samples = struct.unpack(f"<{self.N}h", raw)

                # 1. Normalizar y aplicar ventana Hann
                norm_samples = [(s / 32768.0) * w for s, w in zip(samples, self._hann)]

                # 2. Calcular RMS directo
                sum_sq = sum(s * s for s in norm_samples)
                rms = math.sqrt(sum_sq / self.N)

                # 3. FFT Cooley-Tukey real
                fft_complex = [complex(s, 0.0) for s in norm_samples]
                fft_res = self._fft(fft_complex)
                mags = [abs(c) * (2.0 / self.N) for c in fft_res[:self.N // 2]]

                # 4. Agrupar en 32 bandas logarítmicas con boost dinámico
                spectrum_32 = [0.0] * 32
                for b_idx, (k_min, k_max) in enumerate(self._bandas):
                    bins = mags[k_min:k_max]
                    avg = sum(bins) / max(1, len(bins))
                    val = min(1.0, math.sqrt(avg * 20.0))
                    spectrum_32[b_idx] = round(val, 3)

                # Calcular energías de bandas específicas
                bass = sum(spectrum_32[0:6]) / 6.0
                mids = sum(spectrum_32[6:20]) / 14.0
                treble = sum(spectrum_32[20:32]) / 12.0
                energy = max(bass, (bass * 0.5 + mids * 0.35 + treble * 0.15), max(spectrum_32) * 0.8)

                # Actualizar datos actuales de forma atómica y segura
                payload = {
                    "activo": True,
                    "fuente": self._fuente_actual,
                    "bass": round(min(1.0, bass * 1.5), 3),
                    "mids": round(min(1.0, mids * 1.4), 3),
                    "treble": round(min(1.0, treble * 1.3), 3),
                    "energy": round(min(1.0, energy * 1.5), 3),
                    "rms": round(rms, 4),
                    "spectrum": spectrum_32
                }

                with self._lock:
                    self.datos_actuales = payload

                # ~50 FPS (20ms)
                time.sleep(0.015)

            except Exception as e:
                time.sleep(0.05)


# Instancia singleton global para el backend
audio_monitor = AudioMonitorNativo()

