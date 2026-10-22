#!/usr/bin/env bash
# ==============================================================================
# instalar_pdfium.sh — PDFium (el motor de PDF de Chrome) para leer los libros de la biblioteca
#
#   Lo usa backend-rust/crates/prig-biblioteca (pdf.rs) desde lib/pdfium/libpdfium.so. Medido con un libro de
#   864 páginas: 1,7 s (pypdf: ~14 s en serie), con el texto igual o mejor. Sin él, Prig sigue con pypdf.
#   Binarios de github.com/bblanchon/pdfium-binaries, versión fija y comprobada por sha256.
# ==============================================================================
set -euo pipefail
VERSION="chromium/8100"
SHA256="1c1894a12d4d96ee01400c3874444126254180c5c7d2ab628576b67f8120320a"
PRIG_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESTINO="${PRIG_ROOT}/lib/pdfium"
if [ -f "${DESTINO}/libpdfium.so" ] && [ "$(cat "${DESTINO}/VERSION_PRIG" 2>/dev/null)" = "${VERSION}" ]; then
    echo "✅ PDFium ${VERSION} ya está en ${DESTINO}"
    exit 0
fi
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
echo "⬇️  PDFium ${VERSION}…"
curl -fsSL -o "$TMP/pdfium.tgz" "https://github.com/bblanchon/pdfium-binaries/releases/download/${VERSION/\//%2F}/pdfium-linux-x64.tgz"
echo "${SHA256}  $TMP/pdfium.tgz" | sha256sum -c --quiet
tar xzf "$TMP/pdfium.tgz" -C "$TMP"
mkdir -p "$DESTINO"
cp "$TMP/lib/libpdfium.so" "$DESTINO/"
cp "$TMP/LICENSE" "$DESTINO/" 2>/dev/null || true
echo "$VERSION" > "$DESTINO/VERSION_PRIG"
echo "✅ PDFium ${VERSION} en ${DESTINO}"
