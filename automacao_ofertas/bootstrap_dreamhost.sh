#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
VENV_DIR="$SCRIPT_DIR/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "Bootstrap do dashboard em: $SCRIPT_DIR"

if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "Criando virtualenv em $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

echo "Atualizando pip"
"$VENV_DIR/bin/python" -m pip install --upgrade pip

echo "Instalando dependencias do dashboard"
"$VENV_DIR/bin/python" -m pip install -r "$SCRIPT_DIR/requirements.txt"

echo "Atualizando yt-dlp"
"$VENV_DIR/bin/python" -m pip install --upgrade yt-dlp

echo "Versoes ativas:"
"$VENV_DIR/bin/python" --version
"$VENV_DIR/bin/python" -c "import yt_dlp; print('yt-dlp', yt_dlp.version.__version__)"
