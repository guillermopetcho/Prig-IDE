"""Diferencial del monitor de audio: el análisis de Python puro (commit de referencia) contra el de Rust, trozo a
trozo (silencio, amplitud máxima, tonos, ruido), y el listado de aplicaciones con un pactl falso.
Uso: .venv/bin/python audio.py [semilla] [trozos]"""
import json, math, os, random, struct, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _referencia  # noqa: E402
import audio_monitor as an  # noqa: E402
import prig_nativo  # noqa: E402

R = random.Random(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
TROZOS = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
viejo = _referencia.audio_viejo.AudioMonitorNativo()


def analizar_python(raw, fuente):
    """ El cuerpo del bucle de captura de Python, tal cual """
    self = viejo
    samples = struct.unpack(f"<{self.N}h", raw)
    norm_samples = [(s / 32768.0) * w for s, w in zip(samples, self._hann)]
    rms = math.sqrt(sum(s * s for s in norm_samples) / self.N)
    fft_res = self._fft([complex(s, 0.0) for s in norm_samples])
    mags = [abs(c) * (2.0 / self.N) for c in fft_res[:self.N // 2]]
    spectrum_32 = [0.0] * 32
    for b_idx, (k_min, k_max) in enumerate(self._bandas):
        bins = mags[k_min:k_max]
        spectrum_32[b_idx] = round(min(1.0, math.sqrt(sum(bins) / max(1, len(bins)) * 20.0)), 3)
    bass = sum(spectrum_32[0:6]) / 6.0
    mids = sum(spectrum_32[6:20]) / 14.0
    treble = sum(spectrum_32[20:32]) / 12.0
    energy = max(bass, (bass * 0.5 + mids * 0.35 + treble * 0.15), max(spectrum_32) * 0.8)
    return {"activo": True, "fuente": fuente, "bass": round(min(1.0, bass * 1.5), 3), "mids": round(min(1.0, mids * 1.4), 3),
            "treble": round(min(1.0, treble * 1.3), 3), "energy": round(min(1.0, energy * 1.5), 3), "rms": round(rms, 4),
            "spectrum": spectrum_32}


def trozo(tipo):
    if tipo == 0:
        return b"\0" * 1024
    if tipo == 1:
        return struct.pack("<512h", *([32767, -32768] * 256))
    if tipo == 2:
        f, a = R.uniform(30, 7000), R.uniform(10, 32000)
        return struct.pack("<512h", *[int(a * math.sin(2 * math.pi * f * i / 16000)) for i in range(512)])
    if tipo == 3:
        return bytes(R.getrandbits(8) for _ in range(1024))
    a = R.uniform(0, 3000)
    return struct.pack("<512h", *[max(-32768, min(32767, int(R.gauss(0, a)))) for _ in range(512)])


dif = 0
for _ in range(TROZOS):
    raw = trozo(R.randint(0, 4))
    if json.dumps(analizar_python(raw, "sistema_global")) != json.dumps(prig_nativo.audio.analizar(raw, "sistema_global")):
        dif += 1
print(f"análisis: {TROZOS} trozos, {dif} diferencias")

SALIDAS = [
    "Sink Input #12\n\tCorked: no\n\tProperties:\n\t\tapplication.name = \"Firefox\"\n\t\tmedia.name = \"YouTube - Música\"\n"
    "\t\tapplication.process.binary = \"firefox\"\nSink Input #13\n\tCorked: yes\n\tProperties:\n\t\tapplication.name = "
    "\"speech-dispatcher-dummy\"\nSink Input #14\n\tCorked: no\n\tProperties:\n\t\tapplication.process.binary = \"spotify\"\n",
    "Entrada del destino #7\n\tPausado: sí\n\tPropiedades:\n\t\tapplication.name = \"VLC media player\"\n\t\tmedia.name = \"\"\n"
    "Entrada de sumidero #8\n\t\tmedia.name = \"Discord\"\n",
    "", "Sink Input #x\nnada\n", "Sink Input # 21\n\tCorked: TRUE\n\t\tapplication.name = \"Steam\"\n"]
carpeta = tempfile.mkdtemp(dir=_referencia.TMP)
with open(os.path.join(carpeta, "pactl"), "w") as f:
    f.write('#!/bin/sh\ncat "$PACTL_SALIDA"\n')
os.chmod(os.path.join(carpeta, "pactl"), 0o755)
os.environ["PATH"] = carpeta + ":" + os.environ["PATH"]
distintas = 0
for k, salida in enumerate(SALIDAS):
    ruta = os.path.join(carpeta, "salida.txt")
    with open(ruta, "w") as f:
        f.write(salida)
    os.environ["PACTL_SALIDA"] = ruta
    for fuente in ("sistema_global", "12", "7"):
        viejo._fuente_actual = fuente
        nuevo = an.AudioMonitorNativo()
        nuevo.seleccionar_fuente(fuente)
        if viejo.listar_aplicaciones_audio() != nuevo.listar_aplicaciones_audio():
            distintas += 1
print(f"listados: {len(SALIDAS) * 3} comparados, {distintas} distintos")
