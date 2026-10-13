#!/bin/bash
# Re-medición después de implementar las 5 propuestas de T7 (docs/estudio-banco.md): las preguntas que decidían el
# modo, dos veces en cada modo, el control, y B6 de E8 (la clave mal escrita)
export PRIG_SISTEMA=$HOME/.cache/prig-estudio/sistema/68a29512642ffa9d
T=$HOME/.cache/prig-estudio/t7
cd /home/ama-gi/Prig
for corrida in "prig $HOME/.cache/prig-estudio/repos/Prig" "e8 $HOME/.cache/prig-estudio/repos-e8/Prig"; do
  set -- $corrida
  echo "=== $(date '+%H:%M:%S') re-medición $1" >> $T/serie_r.log
  .venv/bin/python docs/estudio-banco/sonda.py "$2" "$T/r_$1_preguntas.json" "$T/r_$1.json" --modo general 2>&1 | grep --line-buffered -v Warning | tee "$T/r_$1.log" >> $T/serie_r.log
  echo "=== $(date '+%H:%M:%S') fin de $1 (código ${PIPESTATUS[0]})" >> $T/serie_r.log
  sleep 15
done
echo "SERIE R COMPLETA" >> $T/serie_r.log
