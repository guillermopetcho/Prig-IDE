"""Línea base del banco, sin modelo: indexar desde cero, sincronizar sin cambios, partir y las consultas típicas.

  .venv/bin/python docs/estudio-banco/linea_base_banco.py [--referencia]

Mide sobre la copia limpia de Prig (la de e8.py) en un banco temporal: no toca el banco real ni llama a Ollama.
Fue la referencia del plan del motor en Rust (docs/plan-banco-rust.md, sección 1). Prig ya usa solo Rust; con
--referencia mide el motor de Python congelado en ~/prig-memoria/referencia.
"""
import os
import shutil
import sqlite3
import sys
import tempfile
import time

SISTEMA = os.environ.get("PRIG_SISTEMA") or "/home/ama-gi/Prig"    # o una copia congelada (congelar_sistema.py)
LIMPIA = os.path.expanduser("~/.cache/prig-estudio/repos/Prig")
sys.path.insert(0, os.path.join(SISTEMA, "backend"))
if "--referencia" in sys.argv:
    sys.path.insert(0, os.path.expanduser("~/prig-memoria/referencia"))

import banco_proyecto as bp            # noqa: E402
import memoria_consulta as mc          # noqa: E402
import particion_proyecto as pp        # noqa: E402

bp.BancoProyecto._embebedor_ok = lambda self: False      # sin vectores: no llama a Ollama

PREGUNTAS = (
    "Si cambio el comportamiento de `historial` (en `backend/progreso.py`), ¿qué endpoints HTTP del backend se ven afectados?",
    "Revisa `Tramo.pico_real` en `backend/recursos/termico.py`. ¿Tiene algún error de programación?",
    "¿Qué funciones o métodos del proyecto leen la clave de configuración `truncar`?",
)


def medir(nombre, f, n=1):
    t0 = time.perf_counter()
    for _ in range(n):
        r = f()
    print(f"{nombre:52} {1000 * (time.perf_counter() - t0) / n:9.1f} ms")
    return r


def main():
    tmp = tempfile.mkdtemp(prefix="prig_linea_base_")
    try:
        b = bp.BancoProyecto(LIMPIA, carpeta=os.path.join(tmp, "banco"))
        medir("indexar Prig desde cero (sincronizar)", lambda: b.sincronizar())
        medir("sincronizar sin cambios", lambda: b.sincronizar())
        medir("partir en unidades", lambda: pp.particionar(b))
        c = sqlite3.connect(f"file:{b.ruta_db}?mode=ro", uri=True)
        c.row_factory = sqlite3.Row
        tokens = c.execute("SELECT SUM(tokens) FROM archivos").fetchone()[0]
        archivos = c.execute("SELECT COUNT(*) FROM archivos").fetchone()[0]
        simbolos = c.execute("SELECT COUNT(*) FROM simbolos").fetchone()[0]
        llamadas = c.execute("SELECT COUNT(*) FROM llamadas").fetchone()[0]
        print(f"proyecto: {archivos} archivos · {tokens:,} tokens · {simbolos:,} símbolos · {llamadas:,} llamadas resueltas")
        api = mc.API(c, LIMPIA, lambda *a, **k: None)
        medir("P.llamadores (grafo + búsqueda por texto)", lambda: api.llamadores("Gestor.radiografia"), 3)
        medir("P.grep en todo el proyecto", lambda: api.grep(r"startswith\("), 3)
        medir("P.donde de una clave", lambda: api.donde("truncar"), 3)
        medir("P.camino entre dos funciones", lambda: api.camino("modelos_borrar_parciales", "librerias_disponibles"), 3)
        medir("P.impacto (grafo + texto, 3 saltos)", lambda: api.impacto("backend/progreso.py:historial"), 3)
        for q in PREGUNTAS:
            medir("hechos de una pregunta: " + q[:28] + "…", lambda: mc.hechos_de_la_pregunta(b, q), 3)
        medir("buscar en el banco (texto completo)", lambda: b.buscar("cuántos expertos calientes cargar", k=12), 3)
        c.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
