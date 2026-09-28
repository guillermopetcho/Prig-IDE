"""Corre un comando manteniendo la CPU bajo OBJETIVO °C: congela y reanuda todos sus procesos.

Sirve para compilar el motor MoE sin calentar el equipo (sin control, compilar CUDA lleva la CPU
a 90–97 °C). Se agrupan los procesos por sesión, no por grupo: ninja lanza cada compilación en
su propio grupo de procesos.

    OBJETIVO=72 python3 termostato.py comando args...
"""
import glob
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
from recursos import frio  # noqa: E402

OBJETIVO = float(os.environ.get("OBJETIVO", "72"))


def temp():
    for h in glob.glob("/sys/class/hwmon/hwmon*"):
        try:
            if open(h + "/name").read().strip() == "coretemp":
                return int(open(h + "/temp1_input").read()) / 1000
        except OSError:
            pass
    return None


def de_la_sesion(sid):
    pids = set()
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                if os.getsid(int(d)) == sid:
                    pids.add(int(d))
            except OSError:
                pass
    return pids


def main():
    p = subprocess.Popen(sys.argv[1:], start_new_session=True)
    pausador, media, fraccion = frio.Pausador(), None, 0.5
    try:
        while p.poll() is None:
            t = temp()
            if t is not None:
                media = t if media is None else 0.3 * t + 0.7 * media
                objetivo = 1.0 if media <= OBJETIVO - 8 else max(frio.MINIMO, (OBJETIVO - media) / 8)
                fraccion = min(fraccion + 0.05, max(fraccion - 0.1, objetivo))
            pausador.fijar(de_la_sesion(p.pid), round(fraccion, 2))
            time.sleep(1)
    finally:
        pausador.cerrar()
    sys.exit(p.returncode)


if __name__ == "__main__":
    main()
