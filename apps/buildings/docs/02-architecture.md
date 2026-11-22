# Architecture

```
React 19 + react-konva (2D)  ── lazy three.js (3D preview)
        │  REST/JSON (/api)
FastAPI (1 Uvicorn worker) ── JobManager (1 running job, queue ≤ 4 → 429, SQLite-persisted)
        │
        ├─ schema.py       internal Pydantic v2 project (schema_version=1), Blender-independent
        ├─ bim/debim_adapter.py   ONLY module importing debim (manifest → SpatialResolver → metres model)
        ├─ bim/modules.py  module defaults (stored in metres, converted to project units; `overrides` respected)
        ├─ geometry/       numpy meshes: walls with real openings (shapely triangulation), floors, roofs, stairs,
        │                  columns, beams; per-element .npz cache + fingerprints (dirty-element rebuild);
        │                  collision decomposition
        └─ blender/runner.py → subprocess  blender_scripts/worker.py (bpy): materials, cleanup, optimize,
                               UV, collision, LOD, pivot, export GLB/glTF/FBX/.blend. Closed after each job.
Storage: data/projects/<id>/project.json (atomic write + .bak), meshes/, exports/; data/bim.sqlite3 (index, jobs)
```
Key decisions: Blender never runs in the API process (bpy import ≈ +254 MB); the runner enforces timeout, RSS limit, cancel and process-group kill. Geometry is generated in numpy so previews and collision work without Blender.

## REST endpoints
GET /api/health, /api/system, /api/perf, /api/modules/{pid}; projects: POST/GET /api/projects, GET/PUT/DELETE /api/projects/{pid}, GET .../files/{path}, textures GET/PUT/DELETE; POST /api/geometry/validate, /api/geometry/generate; POST /api/build, /api/build/preview, GET /api/build/status|result/{jid}, POST /api/build/cancel/{jid}; POST /api/assets/{optimize,collision,lod,uv}; POST /api/export/{glb,gltf,fbx}. Errors are `{what, where, why, fix}`. Interactive docs at /docs.
