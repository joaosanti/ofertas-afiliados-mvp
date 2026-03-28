#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"

echo "Importacao automatica do Mercado Livre desativada temporariamente."
exit 0

if [ ! -x "$PYTHON_BIN" ]; then
  echo "Python do virtualenv nao encontrado em $PYTHON_BIN" >&2
  exit 1
fi

cd "$SCRIPT_DIR"
exec "$PYTHON_BIN" run_job.py import --provider mercadolivre
