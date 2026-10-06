#!/bin/bash
# Repeticiones para medir el ruido del muestreo: corre los lotes indicados con --rep, cada uno en su proceso, y se
# detiene en el primero que falle. Los lotes se eligieron al azar con semilla fija (random.Random(7): 3 y 6).
# Uso: serie_rep.sh prig 3 6
QUE=$1; shift
C=$HOME/.cache/prig-estudio/e7/serie_$QUE.log
cd /home/ama-gi/Prig
for N in "$@"; do
  L=$(printf "$HOME/.cache/prig-estudio/e7/lote_%s_%02d_rep.log" $QUE $N)
  echo "=== $(date '+%H:%M:%S') lote $N de $QUE (repetición)" | tee $L >> $C
  .venv/bin/python docs/estudio-banco/lote.py correr $QUE $N --rep 2>&1 | grep --line-buffered -v Warning | tee -a $L >> $C
  R=${PIPESTATUS[0]}
  echo "=== $(date '+%H:%M:%S') fin del lote $N, repetición (código $R)" | tee -a $L >> $C
  if [ $R -ne 0 ]; then echo "SERIE DETENIDA en la repetición del lote $N" | tee -a $L >> $C; exit $R; fi
  sleep 20
done
echo "SERIE COMPLETA repeticiones $QUE $*" >> $C
