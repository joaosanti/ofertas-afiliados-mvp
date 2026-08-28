#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "Python do virtualenv nao encontrado em $PYTHON_BIN" >&2
  exit 1
fi

AMAZON_LIMIT=${AMAZON_LIMIT:-0}
MERCADOLIVRE_LIMIT=${MERCADOLIVRE_LIMIT:-0}
SHOPEE_LIMIT=${SHOPEE_LIMIT:-0}
SHOPEE_VIDEO_STATE=${SHOPEE_VIDEO_STATE:-all}
MAX_IMAGES=${MAX_IMAGES:-5}

cd "$SCRIPT_DIR"
exec "$PYTHON_BIN" run_job.py refresh-catalog \
  --amazon-limit "$AMAZON_LIMIT" \
  --mercadolivre-limit "$MERCADOLIVRE_LIMIT" \
  --shopee-limit "$SHOPEE_LIMIT" \
  --shopee-video-state "$SHOPEE_VIDEO_STATE" \
  --max-images "$MAX_IMAGES"
