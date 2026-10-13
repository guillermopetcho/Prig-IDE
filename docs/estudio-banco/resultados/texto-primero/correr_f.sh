#!/bin/bash
# Medición del modo por defecto (auto) después de las propuestas de T7 y de los hechos de constantes y caminos
export PRIG_SISTEMA=$HOME/.cache/prig-estudio/sistema/9da66efaa6bc0737
T=$HOME/.cache/prig-estudio/t7
cd /home/ama-gi/Prig
for corrida in "prig $HOME/.cache/prig-estudio/repos/Prig" "e8 $HOME/.cache/prig-estudio/repos-e8/Prig"; do
  set -- $corrida
  echo "=== $(date '+%H:%M:%S') fallos $1" >> $T/serie_f.log
  .venv/bin/python docs/estudio-banco/sonda.py "$2" "$T/f_$1_preguntas.json" "$T/f_$1.json" --modo auto 2>&1 | grep --line-buffered -v Warning | tee "$T/f_$1.log" >> $T/serie_f.log
  echo "=== $(date '+%H:%M:%S') fin de $1 (código ${PIPESTATUS[0]})" >> $T/serie_f.log
  sleep 15
done
echo "SERIE F COMPLETA" >> $T/serie_f.log
