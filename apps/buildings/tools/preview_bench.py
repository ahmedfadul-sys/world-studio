"""Time the 3D-preview build: fast in-process GLB path vs the old Blender path.

  .venv/bin/python -I tools/preview_bench.py [--sizes small,medium,large]
"""
import argparse, json, os, sys, tempfile, threading, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend")); sys.path.insert(0, str(ROOT / "tools"))
from bimgame.config import Settings
from bimgame.services.build import BuildService
from bimgame.services.storage import ProjectStore
from perf_run import SIZES, synth

ap = argparse.ArgumentParser(); ap.add_argument("--sizes", default="small,medium,large"); a = ap.parse_args()
with tempfile.TemporaryDirectory() as td:
    s = Settings(data_dir=Path(td)); store = ProjectStore(s); bs = BuildService(store, s)
    for size in a.sizes.split(","):
        lv, nx, ny = SIZES[size]; p = synth(size, lv, nx, ny); store.save(p)
        for mode in ("fast", "blender"):
            os.environ["BIM_PREVIEW_BLENDER"] = "1" if mode == "blender" else "0"
            for i, force in enumerate((True, False)):
                t = time.perf_counter(); r = bs.run(f"{size}{mode}{i}0000", p.id, "preview", {"force": force}, threading.Event())
                print(json.dumps({"size": size, "elements": len(p.elements), "mode": mode, "geometry": "cold" if force else "cached",
                                  "total_s": round(time.perf_counter() - t, 2), "geometry_s": r["geometry"]["seconds"],
                                  "tris": r["triangles"]["visual"], "kb": round(r["validation"]["files"][0]["bytes"] / 1024)}), flush=True)
