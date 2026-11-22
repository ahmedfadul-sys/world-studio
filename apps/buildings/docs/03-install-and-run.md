# Install & run

Requirements: Python 3.13 (API), Python 3.11 (only for the `bpy` pip module) or a Blender binary (`BIM_BLENDER_CMD`), Node 20+.

```
scripts/install.sh      # venvs + deps + frontend build
scripts/start.sh        # http://127.0.0.1:8000  (UI + API in one process)
scripts/test.sh         # pytest + vitest
```
Env vars: `BIM_DATA_DIR`, `BIM_BLENDER_CMD` (real Blender; otherwise `.venv-blender` is used), `BIM_BLENDER_PYTHON`, `BIM_BLENDER_TIMEOUT` (300), `BIM_BLENDER_MAX_RSS_MB` (3500), `BIM_FRONTEND_DIST`.
Dev UI: `cd frontend && npm run dev` (proxies /api to :8000). Windows: `scripts/start.bat` (not tested).
Demo: import `examples/demo_house.json` (create a project, PUT the JSON) — exported result `examples/demo_house.glb` was produced by the real pipeline.
