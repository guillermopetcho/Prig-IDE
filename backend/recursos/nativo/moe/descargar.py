"""Descarga en paralelo por rangos, con reanudación.

    python3 descargar.py URL DESTINO [hilos]

Partes de 64 MB; las terminadas se anotan en DESTINO.partes. Si DESTINO ya existe sin ese archivo
(p. ej. de curl -C -), sus primeros bytes se dan por buenos.
"""
import json, os, sys, threading, time, urllib.request

PARTE = 64 * 1024 * 1024
UA = {"User-Agent": "prig-moe/1.0"}


def tamano_y_url(url):
    r = urllib.request.urlopen(urllib.request.Request(url, headers={**UA, "Range": "bytes=0-0"}), timeout=60)
    total = int(r.headers["Content-Range"].split("/")[1])
    return total, r.geturl()


def main():
    url, destino = sys.argv[1], sys.argv[2]
    hilos = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    total, final = tamano_y_url(url)
    estado = destino + ".partes"
    hechas = set(json.load(open(estado))) if os.path.exists(estado) else set()
    if not os.path.exists(estado) and os.path.exists(destino):
        previo = os.path.getsize(destino)
        hechas = {i for i in range((total + PARTE - 1) // PARTE) if (i + 1) * PARTE <= previo}
    fd = os.open(destino, os.O_RDWR | os.O_CREAT)
    os.ftruncate(fd, total)
    pendientes = [i for i in range((total + PARTE - 1) // PARTE) if i not in hechas]
    cerrojo = threading.Lock()
    bajados = [0]

    def trabajar():
        while True:
            with cerrojo:
                if not pendientes:
                    return
                i = pendientes.pop(0)
            ini, fin = i * PARTE, min(total, (i + 1) * PARTE) - 1
            for intento in range(20):
                try:
                    r = urllib.request.urlopen(urllib.request.Request(
                        final, headers={**UA, "Range": f"bytes={ini}-{fin}"}), timeout=120)
                    datos = r.read()
                    if len(datos) != fin - ini + 1:
                        raise IOError("parte incompleta")
                    os.pwrite(fd, datos, ini)
                    with cerrojo:
                        hechas.add(i)
                        bajados[0] += len(datos)
                        json.dump(sorted(hechas), open(estado, "w"))
                    break
                except Exception:
                    time.sleep(3 + intento)
            else:
                print("no se pudo bajar la parte", i, file=sys.stderr)

    t0 = time.time()
    ts = [threading.Thread(target=trabajar, daemon=True) for _ in range(hilos)]
    for t in ts:
        t.start()
    while any(t.is_alive() for t in ts):
        time.sleep(30)
        print(f"{os.path.basename(destino)}: {len(hechas)}/{(total + PARTE - 1) // PARTE} partes · "
              f"{bajados[0] / max(1, time.time() - t0) / 1e6:.0f} MB/s", flush=True)
    os.close(fd)
    completo = len(hechas) == (total + PARTE - 1) // PARTE
    if completo:
        os.remove(estado)
    print("completo" if completo else "INCOMPLETO", destino)


if __name__ == "__main__":
    main()
