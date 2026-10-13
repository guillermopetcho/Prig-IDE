#!/usr/bin/env bash
# ==============================================================================
# compilar_wasm.sh — Compilador del Motor Gráfico WebAssembly de Prig
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRIG_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
GRAFICOS_DIR="${PRIG_ROOT}/prig-graficos"
OUT_DIR="${PRIG_ROOT}/frontend/wasm"

export PATH="$HOME/.cargo/bin:$PATH"

echo "⚡ [Prig-Graficos] Iniciando compilación de WebAssembly..."

mkdir -p "${OUT_DIR}"

cd "${GRAFICOS_DIR}"
wasm-pack build crates/prig-render-wasm \
    --target web \
    --out-dir "${OUT_DIR}" \
    --release

# wasm-pack deja un .gitignore con «*» en la carpeta de salida: sin quitarlo, el motor no entra en git y un clon nuevo
# de Prig arranca sin él (cae al modo JS). El frontend lo carga de aquí (/static/wasm/ → frontend/wasm/).
rm -f "${OUT_DIR}/.gitignore"

ls -lh "${OUT_DIR}"/prig_render_wasm_bg.wasm "${OUT_DIR}"/prig_render_wasm.js
echo "✅ [Prig-Graficos] Compilación exitosa en ${OUT_DIR}"


