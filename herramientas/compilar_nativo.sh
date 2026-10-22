#!/usr/bin/env bash
# ==============================================================================
# compilar_nativo.sh — Compila la parte en Rust de Prig (backend-rust)
#
#   · prig: la ventana de Prig y dueña de todo (run.sh la usa si existe; si no, main.py)
#   · prig-server: el servidor que sirve la interfaz (main.py lo arranca si existe)
#   · prig_nativo: los subsistemas ya portados, como módulo del Python de Prig
#     (docs/plan-prig-rust.md, 4.1). Sin él no arranca el modo frío.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRIG_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV="${PRIG_ROOT}/.venv"

export PATH="$HOME/.cargo/bin:${VENV}/bin:$PATH"

bash "${SCRIPT_DIR}/instalar_pdfium.sh" || echo "⚠️  PDFium no se pudo instalar: los libros se leen con pypdf"

echo "⚙️  [backend-rust] prig-server..."
cargo build --release --manifest-path "${PRIG_ROOT}/backend-rust/Cargo.toml" -p prig-server

# La ventana necesita los paquetes de desarrollo de WebKitGTK (libwebkit2gtk-4.1-dev); sin ellos, main.py
if pkg-config --exists webkit2gtk-4.1 2>/dev/null; then
    echo "⚙️  [backend-rust] prig (la ventana)..."
    cargo build --release --manifest-path "${PRIG_ROOT}/backend-rust/Cargo.toml" -p prig-ventana
else
    echo "ℹ️  Sin libwebkit2gtk-4.1-dev no se compila la ventana en Rust: se sigue usando main.py"
fi

echo "⚙️  [backend-rust] prig_nativo → ${VENV}..."
cd "${PRIG_ROOT}/backend-rust/crates/prig-nativo-py"
VIRTUAL_ENV="${VENV}" maturin develop --release

"${VENV}/bin/python" -c "import sys; sys.path.insert(0, '${PRIG_ROOT}/backend'); from nativo_rust import rust; print('✅ prig_nativo, interfaz', rust().INTERFAZ)"
