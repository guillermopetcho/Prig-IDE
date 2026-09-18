#!/bin/bash
set -e

SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR="$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
DIR="$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

export PATH="$DIR/bin:$DIR/bin/bin:$HOME/.local/bin:$PATH"

echo "=========================================="
echo "      🚀 Iniciando Prig IDE (Ubuntu)     "
echo "=========================================="

# Localizar el mejor binario de Ollama
OLLAMA_BIN=""
if [ -f "$DIR/bin/ollama" ] && [ -x "$DIR/bin/ollama" ]; then
    OLLAMA_BIN="$DIR/bin/ollama"
elif [ -f "$DIR/bin/bin/ollama" ] && [ -x "$DIR/bin/bin/ollama" ]; then
    OLLAMA_BIN="$DIR/bin/bin/ollama"
elif [ -f "$HOME/.local/bin/ollama" ] && [ -x "$HOME/.local/bin/ollama" ]; then
    OLLAMA_BIN="$HOME/.local/bin/ollama"
elif command -v ollama &> /dev/null; then
    OLLAMA_BIN="$(command -v ollama)"
fi

# Auto-iniciar o actualizar servicio Ollama
if ! curl -s http://127.0.0.1:11434/api/tags &> /dev/null; then
    if [ -n "$OLLAMA_BIN" ]; then
        echo "🤖 Iniciando motor de IA Ollama..."
        nohup "$OLLAMA_BIN" serve > /tmp/ollama.log 2>&1 &
        sleep 2
    fi
else
    # Si ya está activo, comprobar si el binario local es más nuevo que el servicio activo
    RUNNING_VER=$(curl -s http://127.0.0.1:11434/api/version | grep -oP '(?<="version":")[^"]*' || true)
    LOCAL_VER=""
    if [ -n "$OLLAMA_BIN" ]; then
        LOCAL_VER=$("$OLLAMA_BIN" --version 2>&1 | grep -oP '\d+\.\d+[\.\d]*' | head -n1 || true)
    fi
    if [ -n "$RUNNING_VER" ] && [ -n "$LOCAL_VER" ] && [ "$RUNNING_VER" != "$LOCAL_VER" ]; then
        # Solo se reinicia el Ollama propio de Prig (bin/ de este directorio). Un
        # Ollama del sistema o de otro usuario no se toca nunca.
        if pgrep -u "$(id -u)" -f "^$DIR/bin/.*ollama serve" > /dev/null; then
            echo "🔄 Actualizando el Ollama de Prig ($RUNNING_VER -> $LOCAL_VER)..."
            pkill -u "$(id -u)" -f "^$DIR/bin/.*ollama serve" 2>/dev/null || true
            sleep 1
            nohup "$OLLAMA_BIN" serve > /tmp/ollama.log 2>&1 &
            sleep 2
        else
            echo "ℹ️  Hay otro Ollama activo ($RUNNING_VER); Prig lo usa tal cual."
        fi
    fi
fi

if curl -s http://127.0.0.1:11434/api/tags &> /dev/null; then
    echo "✅ IA local (Ollama) activa."
else
    echo "⚠️ Servicio de IA local inactivo o cargando..."
fi

# El entorno virtual queda inservible si la versión de python3 del sistema cambia:
# el intérprete pasa a ser la nueva versión pero los paquetes siguen en
# .venv/lib/pythonX.Y/site-packages y no se importa nada. Se detecta y se recrea.
VENV_OK=0
if [ -d ".venv" ]; then
    SYS_PY_VER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    if [ -d ".venv/lib/python${SYS_PY_VER}" ]; then
        VENV_OK=1
    else
        echo "♻️  El entorno virtual se creó con otra versión de Python; recreándolo..."
        rm -rf .venv
    fi
fi

if [ "$VENV_OK" -eq 0 ]; then
    echo "📦 Creando entorno virtual Python..."
    python3 -m venv .venv
fi

source .venv/bin/activate

# Con `set -e`, un fallo de pip (sin conexión, un espejo caído) abortaba el script
# en silencio: el usuario veía "Verificando dependencias..." y nada más. Si Prig ya
# tiene sus dependencias, debe arrancar igual aunque pip no pueda comprobarlas.
echo "🔍 Verificando dependencias..."
if ! python3 -m pip install -q -r requirements.txt 2>/tmp/prig_pip_error.log; then
    echo "⚠️  No se pudieron verificar las dependencias (¿sin conexión?)."
    echo "    Detalle en /tmp/prig_pip_error.log — se intenta arrancar igualmente."
fi

# Comprobación real: ¿están las dependencias imprescindibles?
if ! python3 -c "import fastapi, uvicorn" 2>/dev/null; then
    echo ""
    echo "❌ Faltan dependencias imprescindibles (fastapi/uvicorn) y no se pudieron instalar."
    echo "   Conéctate a internet y ejecuta:  .venv/bin/python -m pip install -r requirements.txt"
    exit 1
fi

# Asegurar registro en el sistema para que GNOME Shell muestre el icono en el dock al ejecutarse
if [ ! -f "$HOME/.local/share/applications/Prig-IDE.desktop" ] && [ -f "$HOME/Escritorio/Prig-IDE.desktop" ]; then
    mkdir -p "$HOME/.local/share/applications"
    cp -f "$HOME/Escritorio/Prig-IDE.desktop" "$HOME/.local/share/applications/Prig-IDE.desktop"
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
fi

# Asegurar comandos en la terminal (~/.local/bin/Prig, prig, prig-ide)
mkdir -p "$HOME/.local/bin"
for cmd in Prig prig prig-ide; do
    cmd_file="$HOME/.local/bin/$cmd"
    if [ ! -f "$cmd_file" ]; then
        cat << EOF > "$cmd_file"
#!/bin/bash
exec "$DIR/run.sh" "\$@"
EOF
        chmod +x "$cmd_file"
    fi
done

echo "✨ Lanzando Prig IDE..."
python3 main.py
