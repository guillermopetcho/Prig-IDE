#!/bin/bash
# T7, segunda tanda (docs/plan-texto-primero/T7-medicion.md: «si el resultado queda parejo o es dudoso»): solo las
# preguntas en que los modos difirieron, otra muestra de cada modo y el general con los hechos al final
export PRIG_SISTEMA=$HOME/.cache/prig-estudio/sistema/c56a384954d20820
T=$HOME/.cache/prig-estudio/t7
cd /home/ama-gi/Prig
for corrida in "t2 prig $HOME/.cache/prig-estudio/repos/Prig t2_prig_preguntas.json" \
               "t2 e8 $HOME/.cache/prig-estudio/repos-e8/Prig t2_e8_preguntas.json"; do
  set -- $corrida
  echo "=== $(date '+%H:%M:%S') $1 $2" >> $T/serie_t2.log
  .venv/bin/python docs/estudio-banco/sonda.py "$3" "$T/$4" "$T/$1_$2.json" --modo general 2>&1 | grep --line-buffered -v Warning | tee "$T/$1_$2.log" >> $T/serie_t2.log
  echo "=== $(date '+%H:%M:%S') fin de $1 $2 (código ${PIPESTATUS[0]})" >> $T/serie_t2.log
  sleep 15
done
echo "SERIE T2 COMPLETA" >> $T/serie_t2.log
