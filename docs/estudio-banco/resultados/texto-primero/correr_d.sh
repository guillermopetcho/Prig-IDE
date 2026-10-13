#!/bin/bash
# Medición del modo por defecto (auto) después de las propuestas de T7 y de los hechos de constantes y caminos
export PRIG_SISTEMA=$HOME/.cache/prig-estudio/sistema/2f2520f6ea435e99
T=$HOME/.cache/prig-estudio/t7
cd /home/ama-gi/Prig
for corrida in "prig $HOME/.cache/prig-estudio/repos/Prig" "e8 $HOME/.cache/prig-estudio/repos-e8/Prig"; do
  set -- $corrida
  echo "=== $(date '+%H:%M:%S') auto $1" >> $T/serie_d.log
  .venv/bin/python docs/estudio-banco/sonda.py "$2" "$T/d_$1_preguntas.json" "$T/d_$1.json" --modo auto 2>&1 | grep --line-buffered -v Warning | tee "$T/d_$1.log" >> $T/serie_d.log
  echo "=== $(date '+%H:%M:%S') fin de $1 (código ${PIPESTATUS[0]})" >> $T/serie_d.log
  sleep 15
done
echo "SERIE D COMPLETA" >> $T/serie_d.log
