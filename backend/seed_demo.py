"""
Datos de siembra para desarrollo.

Sin esto, probar un cambio en el perfil o en el mapa de calor obliga a generar un
plan real con el modelo: entre 30 y 60 segundos por prueba, varias veces al día.
Este script rellena un workspace con datos verosímiles en menos de un segundo.

    python backend/seed_demo.py --workspace /ruta/al/proyecto [--reset]
"""

import os
import sys
import random
import argparse
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from study_plan_engine import (  # noqa: E402
    SeguimientoRepository, SeguimientoPath, SeguimientoBlock,
)
from learning_telemetry import LearningTelemetry  # noqa: E402
from learner_dataset import LearnerDatasetManager  # noqa: E402

RUTAS = [
    ("Aprender Python para ciencia de datos", [
        ("Tipos y estructuras básicas", ["listas", "diccionarios", "tuplas"], "theory"),
        ("Comprensiones y funciones", ["comprensiones de listas", "funciones", "lambda"], "practice"),
        ("NumPy y vectorización", ["numpy", "arrays", "broadcasting"], "practice"),
        ("Pandas: carga y limpieza", ["pandas", "dataframe", "valores nulos"], "practice"),
        ("Visualización", ["matplotlib", "seaborn"], "mixed"),
        ("Proyecto: análisis exploratorio", ["eda", "estadistica descriptiva"], "project"),
    ]),
    ("Fundamentos de machine learning", [
        ("Regresión lineal", ["regresion", "minimos cuadrados"], "theory"),
        ("Separación de datos y validación", ["train test split", "validacion cruzada"], "practice"),
        ("Clasificación", ["regresion logistica", "matriz de confusion"], "practice"),
        ("Regularización y sobreajuste", ["regularizacion", "overfitting"], "mixed"),
    ]),
]

CONCEPTOS_TELEMETRIA = [
    "comprensiones de listas en Python",
    "argumentos por defecto mutables",
    "uso de diccionarios para contar frecuencias",
    "separación de datos en entrenamiento y prueba",
    "manejo de excepciones con try/except",
    "slicing de listas y cadenas",
]

ERRORES = [
    ("AssertionError: assert resultado == esperado", 0.45),
    ("TypeError: unsupported operand type(s)", 0.15),
    ("NameError: name 'total' is not defined", 0.15),
    ("IndexError: list index out of range", 0.15),
    ("SyntaxError: invalid syntax", 0.10),
]


def sembrar(workspace: str, reset: bool = False) -> dict:
    rnd = random.Random(20260914)  # determinista: dos ejecuciones dan lo mismo
    ahora = datetime.now()

    seg_repo = SeguimientoRepository(workspace)
    if reset:
        for f in os.listdir(seg_repo.seg_dir):
            if f.startswith("seg_demo_"):
                os.remove(os.path.join(seg_repo.seg_dir, f))

    creados = []
    for idx, (meta, bloques) in enumerate(RUTAS):
        path = SeguimientoPath(
            id=f"seg_demo_{idx + 1:02d}",
            goal=meta,
            topics_raw=", ".join(t for _, temas, _ in bloques for t in temas),
            rationale="Ruta de demostración generada por seed_demo.py",
            created_at=(ahora - timedelta(days=40 - idx * 10)).isoformat(),
        )
        for b_idx, (titulo, temas, tipo) in enumerate(bloques):
            path.blocks.append(SeguimientoBlock(
                block_id=f"blk_demo_{idx + 1}_{b_idx + 1}",
                title=titulo,
                description=f"Estudio de {titulo.lower()}.",
                learning_objective=f"Ser capaz de aplicar {temas[0]} en un caso real.",
                validation_check=f"Resolver un ejercicio que use {temas[0]} sin ayuda.",
                topics=temas,
                type=tipo,
                estimated_time=f"{rnd.randint(1, 4)} horas",
            ))

        # Completar una parte, con fechas repartidas para que el mapa de calor tenga forma
        completados = path.blocks[: max(1, len(path.blocks) - 2 - idx)]
        for offset, b in enumerate(completados):
            path.completed_blocks.append(b.block_id)
            path.completion_dates[b.block_id] = (
                ahora - timedelta(days=35 - idx * 10 - offset * 3)
            ).isoformat()

        seg_repo.save(path)
        creados.append(path.id)

    # Telemetría: intentos de ejercicios con fallos y aciertos realistas
    tel = LearningTelemetry(workspace)
    eventos = 0
    for dia in range(21, 0, -1):
        if rnd.random() < 0.35:
            continue  # días sin actividad
        # Fechar los eventos en su día real: si todos llevan la fecha de hoy, las
        # métricas temporales (reincidencia, mapa de calor) salen siempre a cero.
        base = ahora - timedelta(days=dia, hours=rnd.randint(0, 8))
        for k in range(rnd.randint(1, 3)):
            concepto = rnd.choice(CONCEPTOS_TELEMETRIA)
            ex_id = f"ex_demo_{rnd.randint(100000, 999999)}"
            momento = base + timedelta(minutes=k * 25)
            tel.record(ex_id, concepto, "generated", created_at=momento)
            intentos = rnd.choices([1, 2, 3], weights=[0.5, 0.3, 0.2])[0]
            for n in range(1, intentos + 1):
                acierto = (n == intentos) and rnd.random() < 0.85
                stderr = "" if acierto else rnd.choices(
                    [e for e, _ in ERRORES], weights=[w for _, w in ERRORES]
                )[0]
                tel.record(ex_id, concepto, "submission", passed=acierto,
                           attempt_num=n, hints_used=0 if n == 1 else rnd.randint(0, 2),
                           stderr=stderr, elapsed=round(rnd.uniform(0.01, 1.5), 3),
                           created_at=momento + timedelta(minutes=2 * n))
                eventos += 1

    LearnerDatasetManager(workspace).build_and_save_dataset()

    return {
        "workspace": os.path.abspath(workspace),
        "seguimientos": creados,
        "eventos_telemetria": eventos,
        "metricas": tel.metrics(days=30),
    }


def main():
    parser = argparse.ArgumentParser(description="Rellena un workspace con datos de demostración")
    parser.add_argument("--workspace", default=os.getcwd())
    parser.add_argument("--reset", action="store_true", help="Borrar los datos de demo anteriores")
    args = parser.parse_args()

    res = sembrar(args.workspace, reset=args.reset)
    m = res["metricas"]
    print(f"\n✨ Workspace sembrado: {res['workspace']}")
    print(f"   seguimientos      : {len(res['seguimientos'])}")
    print(f"   eventos de entrega: {res['eventos_telemetria']}")
    print(f"   acierto al 1er intento: {m['first_try_pass_rate']}%")
    print(f"   ejercicios resueltos  : {m['solve_rate']}%")
    print(f"   perfil de errores     : {m['error_profile']}\n")


if __name__ == "__main__":
    main()
