#!/usr/bin/env bash
# Todos los diferenciales de la plataforma (F2) y de los modelos (F3) con una semilla y pocas vueltas. Ver README.md.
set -euo pipefail
AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$AQUI/../../.venv/bin/python"
SEMILLA="${1:-1}"
cd /tmp
ulimit -v 4000000
for d in "banderas_perfiles 200" "archivos 100" "ide 60" "explorador 150" "inicio 300" "ejecucion 25" "opciones 300" "gestion 120" "buscador 150" "moe 200" "web 200" "indices 40" "troceado 200" "vectores 30" "referencias 100" "desafios 20" "red 150"; do
    set -- $d
    echo "== $1"
    timeout 900 "$PY" -W ignore "$AQUI/$1.py" "$SEMILLA" "$2" | head -4 | cut -c1-600
done
