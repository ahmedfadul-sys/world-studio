#!/usr/bin/env bash
# Single Uvicorn worker on purpose (one heavy build at a time, low RAM).
set -euo pipefail
cd "$(dirname "$0")/../backend"
export BIM_DATA_DIR="${BIM_DATA_DIR:-$(pwd)/../data}"
exec ../.venv/bin/python -m uvicorn bimgame.api.app:app --workers 1 --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}"
