#!/usr/bin/env bash
# Prepara el núcleo Q8 del motor MoE: descarga el Q8_0 de unsloth (37 GB, en paralelo y reanudable),
# verifica su SHA-256 y construye el GGUF híbrido (núcleo Q8 + expertos y vocabulario del Q4
# recortado de Ollama) en ~/.cache/prig-moe/modelos/nucleo-q8-expertos-q4.gguf (21 GB).
# Necesita compilar.sh hecho antes (usa gguf-py del fork). Con --borrar, borra el Q8_0 al final.
set -euo pipefail
AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRIG="$(cd "$AQUI/../../../.." && pwd)"
export PRIG_MOE_TRABAJO="${PRIG_MOE_TRABAJO:-$HOME/.cache/prig-moe}"
MODELOS="$HOME/.cache/prig-moe/modelos"
ARCHIVO="Qwen3.6-35B-A3B-Q8_0.gguf"
SHA="d1a395809f65a43a13ad119eb4e7acdef1ac6d68120f39902c8ab96e72794a59"
mkdir -p "$MODELOS"
cd "$MODELOS"
if [ ! -f "$ARCHIVO" ] || [ -f "$ARCHIVO.partes" ]; then
    python3 "$AQUI/descargar.py" "https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF/resolve/main/$ARCHIVO" "$ARCHIVO" 8
fi
echo "Verificando SHA-256…"
echo "$SHA  $ARCHIVO" | sha256sum -c -
Q4="$(cd "$PRIG/backend" && python3 -c "from ai_engine import motor_moe; print(motor_moe.blob_del_modelo() or '')")"
[ -n "$Q4" ] || { echo "Falta el modelo Q4 de Ollama (hf.co/Elsephire/Qwen3.6-35B-A3B-vocabulary-trimming-GGUF:Q4_K_S)"; exit 1; }
nice -n 19 python3 "$AQUI/construir_nucleo_q8.py" "$Q4" "$ARCHIVO" nucleo-q8-expertos-q4.gguf.nuevo
mv nucleo-q8-expertos-q4.gguf.nuevo nucleo-q8-expertos-q4.gguf
[ "${1:-}" = "--borrar" ] && rm -f "$ARCHIVO"
echo "Listo: $MODELOS/nucleo-q8-expertos-q4.gguf"
