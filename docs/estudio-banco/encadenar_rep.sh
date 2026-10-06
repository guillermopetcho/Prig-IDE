#!/bin/bash
# Espera a que termine la serie (PID dado) y, si terminó completa, lanza las repeticiones 3 y 6
PID=$1; C=$HOME/.cache/prig-estudio/e7/serie_prig.log
while kill -0 $PID 2>/dev/null; do sleep 10; done
sleep 25
if tail -1 $C | grep -q "^SERIE COMPLETA prig"; then
  exec $HOME/.cache/prig-estudio/e7/serie_rep.sh prig 3 6
else
  echo "REPETICIONES NO LANZADAS: la serie no terminó completa" >> $C
fi
