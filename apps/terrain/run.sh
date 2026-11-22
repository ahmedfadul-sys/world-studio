#!/usr/bin/env bash
# يبني الواجهة من جديد ثم يشغّل الأداة على http://localhost:8000
set -e
cd "$(dirname "$0")/frontend"
[ -d node_modules ] || npm install
npm run build
cd ../backend
[ -d .venv ] || { python3 -m venv .venv; . .venv/bin/activate; pip install -r requirements.txt; }
. .venv/bin/activate
uvicorn app.main:app --port 8000
