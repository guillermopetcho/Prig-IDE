#!/usr/bin/env bash
# Todos los diferenciales de backend/recursos con una semilla y pocas vueltas (unos minutos). Ver README.md.
set -euo pipefail
AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$AQUI/../../.venv/bin/python"
SEMILLA="${1:-1}"
cd /tmp
for d in calculo almacen ritmo suave termico servidor calibracion gestor; do
    echo "== $d"
    PRIG_SIN_MOTOR_SUAVE=1 "$PY" "$AQUI/$d.py" "$SEMILLA" 150 | tail -4 | cut -c1-400
done
echo "== audio"; "$PY" "$AQUI/audio.py" "$SEMILLA" 300
echo "== maquina"; "$PY" "$AQUI/maquina.py"
