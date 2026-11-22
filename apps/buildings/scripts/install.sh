#!/usr/bin/env bash
# Installs backend (.venv), Blender worker env (.venv-blender) and builds the frontend.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-python3}
$PY -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
if [ -z "${BIM_BLENDER_CMD:-}" ]; then
  PY311=${PYTHON311:-python3.11}
  if command -v "$PY311" >/dev/null; then
    "$PY311" -m venv .venv-blender
    .venv-blender/bin/pip install -r requirements-blender.txt
  else
    echo "WARN: python3.11 not found; set BIM_BLENDER_CMD to a Blender binary or install Python 3.11 for the bpy module."
  fi
fi
(cd frontend && npm install && npm run build)
echo "Done. Start with scripts/start.sh"
