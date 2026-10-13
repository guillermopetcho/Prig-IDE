#!/usr/bin/env bash
# ==============================================================================
# sincronizar_banco_core.sh — Las dos copias del motor del banco, iguales
# ==============================================================================
# El motor del banco (crate banco-core) vive en ~/prig-memoria (con sus comparadores contra la referencia de
# Python: ~/prig-memoria/herramientas) y hay una copia en backend-rust/crates/banco-core para el servidor en Rust.
# El código tiene que ser el mismo; solo cambia el Cargo.toml (aquí, SQLite incluido: el servidor es otro proceso).
#
#   herramientas/sincronizar_banco_core.sh            → compara y dice si hay diferencias (sale con 1 si las hay)
#   herramientas/sincronizar_banco_core.sh --copiar   → copia src/ y examples/ de ~/prig-memoria a backend-rust
set -euo pipefail

PRIG_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ORIGEN="${PRIG_MEMORIA:-$HOME/prig-memoria}/crates/banco-core"
DESTINO="${PRIG_ROOT}/backend-rust/crates/banco-core"

if [ ! -d "${ORIGEN}/src" ]; then
    echo "No está ${ORIGEN} (PRIG_MEMORIA apunta a otra carpeta): nada que comparar."
    exit 0
fi

if [ "${1:-}" = "--copiar" ]; then
    for sub in src examples; do
        if [ -d "${ORIGEN}/${sub}" ]; then
            rm -rf "${DESTINO:?}/${sub}"
            cp -r "${ORIGEN}/${sub}" "${DESTINO}/${sub}"
        fi
    done
    echo "✅ banco-core copiado de ${ORIGEN}"
fi

if diff -rq "${ORIGEN}/src" "${DESTINO}/src" >/dev/null && diff -rq "${ORIGEN}/examples" "${DESTINO}/examples" >/dev/null 2>&1; then
    echo "✅ Las dos copias de banco-core son iguales."
else
    echo "⚠️  Las copias de banco-core difieren:"
    diff -rq "${ORIGEN}/src" "${DESTINO}/src" || true
    diff -rq "${ORIGEN}/examples" "${DESTINO}/examples" 2>/dev/null || true
    echo "   Para traer la de ~/prig-memoria: herramientas/sincronizar_banco_core.sh --copiar"
    exit 1
fi
