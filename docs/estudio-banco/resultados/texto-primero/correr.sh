#!/bin/bash
# Medición corta del plan «texto primero» (docs/plan-texto-primero/T7-medicion.md): 4 sondas seguidas, cada una en su
# proceso, con el sistema congelado. Un registro común (serie.log) para seguir el avance
export PRIG_SISTEMA=$HOME/.cache/prig-estudio/sistema/c56a384954d20820
T=$HOME/.cache/prig-estudio/t7
cd /home/ama-gi/Prig
for corrida in "prig general $HOME/.cache/prig-estudio/repos/Prig preguntas_prig.json" \
               "prig unidad $HOME/.cache/prig-estudio/repos/Prig preguntas_prig.json" \
               "e8 general $HOME/.cache/prig-estudio/repos-e8/Prig preguntas_e8.json" \
               "e8 unidad $HOME/.cache/prig-estudio/repos-e8/Prig preguntas_e8.json"; do
  set -- $corrida
  echo "=== $(date '+%H:%M:%S') $1 en modo $2" >> $T/serie.log
  .venv/bin/python docs/estudio-banco/sonda.py "$3" "$T/$4" "$T/$1_$2.json" --modo "$2" 2>&1 | grep --line-buffered -v Warning | tee "$T/$1_$2.log" >> $T/serie.log
  echo "=== $(date '+%H:%M:%S') fin de $1 $2 (código ${PIPESTATUS[0]})" >> $T/serie.log
  sleep 15
done
echo "SERIE T7 COMPLETA" >> $T/serie.log
