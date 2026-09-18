"""
Banco de evaluación de agentes.

Sin medición, ajustar un prompt es superstición: se cambia una frase, la respuesta
"parece mejor" y no hay forma de saberlo. Este arnés ejecuta un conjunto de casos
fijos contra un modelo y devuelve un porcentaje comparable entre ejecuciones.

Uso:
    python backend/evals/run_eval.py --model qwen2.5-coder:7b [--limit 5] [--attempts 1]
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_engine import AIEngine          # noqa: E402
from runner import CodeRunner           # noqa: E402
from exercise_engine import ExerciseEngine  # noqa: E402

CASES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cases")
RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def run_exercise_eval(model: str, limit: int = 0, attempts: int = 1, verbose: bool = True) -> dict:
    with open(os.path.join(CASES_DIR, "exercise_generation.json"), encoding="utf-8") as f:
        case = json.load(f)

    concepts = case["concepts"][:limit] if limit else case["concepts"]

    ai = AIEngine()
    runner = CodeRunner(timeout_seconds=15)
    engine = ExerciseEngine(ai, runner)

    rows = []
    started = time.time()

    for idx, concept in enumerate(concepts, 1):
        t0 = time.time()
        row = {"concept": concept, "json_ok": False, "valid": False,
               "reason": "", "attempts": 0, "seconds": 0.0}
        try:
            result = engine.generate_validated(concept, model=model, attempts=attempts)
            row["attempts"] = len([h for h in result["history"] if h["stage"] == "validation"]) or attempts
            row["json_ok"] = any(h["stage"] == "validation" for h in result["history"])
            row["valid"] = result["ok"]
            if result["ok"]:
                row["reason"] = "OK"
            else:
                last = result["history"][-1] if result["history"] else {}
                row["reason"] = last.get("reason") or last.get("error", "desconocido")
        except Exception as err:
            row["reason"] = f"excepción: {err}"

        row["seconds"] = round(time.time() - t0, 1)
        rows.append(row)

        if verbose:
            mark = "✓" if row["valid"] else "✗"
            print(f"  [{idx:2}/{len(concepts)}] {mark} {concept[:44]:46} "
                  f"{row['seconds']:5.1f}s  {row['reason'][:52]}")

    runner.sessions.shutdown_all()

    total = len(rows)
    valid = sum(1 for r in rows if r["valid"])
    json_ok = sum(1 for r in rows if r["json_ok"])

    summary = {
        "eval": "exercise_generation",
        "model": model,
        "run_at": datetime.now().isoformat(),
        "total": total,
        "json_parse_rate": round(json_ok / total * 100, 1) if total else 0.0,
        "valid_rate": round(valid / total * 100, 1) if total else 0.0,
        "attempts_per_exercise": attempts,
        "elapsed_seconds": round(time.time() - started, 1),
        "failure_reasons": {},
        "rows": rows,
    }
    for r in rows:
        if not r["valid"]:
            key = r["reason"][:70]
            summary["failure_reasons"][key] = summary["failure_reasons"].get(key, 0) + 1

    os.makedirs(RESULTS_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = os.path.join(RESULTS_DIR, f"exercise_generation_{model.replace(':', '_')}_{stamp}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    summary["saved_to"] = out
    return summary


def main():
    parser = argparse.ArgumentParser(description="Banco de evaluación de agentes de Prig")
    parser.add_argument("--model", default="qwen2.5-coder:7b")
    parser.add_argument("--limit", type=int, default=0, help="Usar solo los N primeros conceptos")
    parser.add_argument("--attempts", type=int, default=1, help="Reintentos por concepto")
    args = parser.parse_args()

    print(f"\n=== S1: generación de ejercicios verificables — modelo {args.model} ===\n")
    s = run_exercise_eval(args.model, limit=args.limit, attempts=args.attempts)

    print(f"\n  JSON válido        : {s['json_parse_rate']}%")
    print(f"  EJERCICIOS VÁLIDOS : {s['valid_rate']}%   <-- la cifra que decide el producto")
    print(f"  tiempo             : {s['elapsed_seconds']}s ({s['elapsed_seconds']/max(1,s['total']):.1f}s por ejercicio)")
    if s["failure_reasons"]:
        print("\n  Motivos de fallo:")
        for reason, n in sorted(s["failure_reasons"].items(), key=lambda x: -x[1]):
            print(f"    {n:2}x  {reason}")
    print(f"\n  Guardado en: {s['saved_to']}\n")


if __name__ == "__main__":
    main()
