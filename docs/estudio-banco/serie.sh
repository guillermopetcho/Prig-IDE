#!/bin/bash
# Corre los lotes DESDE..HASTA de una serie, cada uno en su propio proceso; se detiene en el primero que no
# pase los chequeos previos o la verificación. Uso: serie.sh prig 1 15
QUE=$1; DESDE=$2; HASTA=$3
C=$HOME/.cache/prig-estudio/e7/serie_$QUE.log
cd /home/ama-gi/Prig
for N in $(seq $DESDE $HASTA); do
  L=$(printf "$HOME/.cache/prig-estudio/e7/lote_%s_%02d.log" $QUE $N)
  echo "=== $(date '+%H:%M:%S') lote $N de $QUE" | tee $L >> $C
  .venv/bin/python docs/estudio-banco/lote.py correr $QUE $N 2>&1 | grep --line-buffered -v Warning | tee -a $L >> $C
  R=${PIPESTATUS[0]}
  echo "=== $(date '+%H:%M:%S') fin del lote $N (código $R)" | tee -a $L >> $C
  if [ $R -ne 0 ]; then echo "SERIE DETENIDA en el lote $N" | tee -a $L >> $C; exit $R; fi
  sleep 20
done
echo "SERIE COMPLETA $QUE $DESDE-$HASTA" >> $C
