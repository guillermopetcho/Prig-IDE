#!/usr/bin/env bash
# Compila el motor MoE de Prig: llama.cpp con expertos calientes en VRAM.
#
#   Base:   JigSawPT/llama.cpp, rama aipc-hardening (moe-autopilot), commit fijo
#   Parche: prig-moe.diff (la CPU omite los expertos que ya calculó la GPU, sin relleno en VRAM)
#   Destino: <Prig>/lib/moe  (binarios y bibliotecas de CUDA; git lo ignora, como lib/ollama)
#
# No necesita root: el compilador de CUDA se instala con micromamba en la carpeta de trabajo.
# Compila bajo un termostato (72 °C) en los núcleos E con prioridad baja.
#
#   PRIG_MOE_TRABAJO  carpeta de trabajo (por defecto ~/.cache/prig-moe)
#   PRIG_MOE_ARCH     arquitectura CUDA (por defecto, la de la GPU; 89 = RTX 40xx)
set -euo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRIG="$(cd "$AQUI/../../../.." && pwd)"
TRABAJO="${PRIG_MOE_TRABAJO:-$HOME/.cache/prig-moe}"
DESTINO="$PRIG/lib/moe"
REPO="https://github.com/JigSawPT/llama.cpp"
RAMA="aipc-hardening"
COMMIT="cf632264a"
CUDA="12.9"

mkdir -p "$TRABAJO"
cd "$TRABAJO"

arch="${PRIG_MOE_ARCH:-}"
if [ -z "$arch" ]; then
    arch="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -1 | tr -d '.')"
    arch="${arch:-89}"
fi

echo "== 1/4 Compilador de CUDA $CUDA (sin root)"
if [ ! -x cudaenv/bin/nvcc ]; then
    if [ ! -x bin/micromamba ]; then
        curl -sL https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xj bin/micromamba
    fi
    MAMBA_ROOT_PREFIX="$TRABAJO/mamba" ./bin/micromamba create -y -q -p "$TRABAJO/cudaenv" -c conda-forge \
        "cuda-nvcc=$CUDA" "cuda-cudart-dev=$CUDA" "libcublas-dev=$CUDA" "cuda-cccl=$CUDA" "cuda-version=$CUDA" \
        cmake ninja patchelf
fi
if [ ! -x cudaenv/bin/patchelf ]; then
    MAMBA_ROOT_PREFIX="$TRABAJO/mamba" ./bin/micromamba install -y -q -p "$TRABAJO/cudaenv" -c conda-forge patchelf
fi
export PATH="$TRABAJO/cudaenv/bin:$PATH"

echo "== 2/4 Código: $REPO ($RAMA @ $COMMIT) + parche de Prig"
if [ ! -d fork/.git ]; then
    git clone -q --filter=blob:none -b "$RAMA" "$REPO" fork
fi
cd fork
if [ "$(git rev-parse --short=9 HEAD)" != "$COMMIT" ]; then
    git fetch -q origin "$RAMA"
    git checkout -q -f "$COMMIT"
fi
git checkout -q -- .
git apply "$AQUI/prig-moe.diff"

echo "== 3/4 Compilación (sm_$arch, núcleos E, termostato a 72 °C)"
cmake -S . -B build -G Ninja -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES="$arch" \
    -DCMAKE_CUDA_COMPILER="$TRABAJO/cudaenv/bin/nvcc" -DCUDAToolkit_ROOT="$TRABAJO/cudaenv" \
    -DCMAKE_CUDA_HOST_COMPILER="$(command -v g++)" -DGGML_NATIVE=ON -DLLAMA_CURL=OFF \
    -DLLAMA_BUILD_TESTS=OFF -DCMAKE_BUILD_TYPE=Release >/dev/null
NUCLEOS_E="$(python3 -c "
import sys; sys.path.insert(0, '$PRIG/backend')
from recursos import frio; print(','.join(map(str, frio.nucleos_eficientes())) or '')")"
TASKSET=()
[ -n "$NUCLEOS_E" ] && TASKSET=(taskset -c "$NUCLEOS_E")
OBJETIVO=72 python3 "$AQUI/termostato.py" "${TASKSET[@]}" nice -n 19 \
    cmake --build build -j4 --target llama-server

echo "== 4/4 Instalación en $DESTINO"
rm -rf "$DESTINO.nuevo"
mkdir -p "$DESTINO.nuevo"
cp -a build/bin/llama-server "$DESTINO.nuevo/"
cp -a build/bin/*.so* "$DESTINO.nuevo/"
for lib in libcudart.so.12 libcublas.so.12 libcublasLt.so.12; do
    cp -aL "$TRABAJO/cudaenv/lib/$lib" "$DESTINO.nuevo/"
done
# Cada binario busca sus bibliotecas solo junto a sí mismo (no en la carpeta de compilación)
for f in "$DESTINO.nuevo"/llama-server "$DESTINO.nuevo"/*.so*; do
    [ -L "$f" ] || patchelf --set-rpath '$ORIGIN' "$f"
done
{
    echo "base=$REPO@$COMMIT"
    echo "parche=$(sha256sum "$AQUI/prig-moe.diff" | cut -c1-16)"
    echo "cuda=$CUDA sm_$arch"
    echo "compilado=$(date -Iseconds)"
} > "$DESTINO.nuevo/VERSION"
rm -rf "$DESTINO"
mv "$DESTINO.nuevo" "$DESTINO"
echo "Listo: $DESTINO"
