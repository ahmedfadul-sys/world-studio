"""Performance / memory test: small, medium, large synthetic buildings.

  .venv/bin/python -I tools/perf_run.py [--sizes small,medium,large] [--repeat 3] [--out docs/perf.json]

Reports per run: RAM before / peak / after (backend process tree incl. Blender),
Blender-only peak RSS, wall time, project size, element count, triangles.
Also checks that no Blender process survives and that repeated builds do not grow RSS.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from bimgame.config import Settings  # noqa: E402
from bimgame.schema import (Column, Door, Floor, Level, Project, Roof, Wall, Window,  # noqa: E402
                            new_project)
from bimgame.services.build import BuildService  # noqa: E402
from bimgame.services.storage import ProjectStore  # noqa: E402
from bimgame.utils.memprof import measure  # noqa: E402

SIZES = {"small": (1, 2, 2), "medium": (3, 4, 4), "large": (8, 7, 7)}  # levels, rooms_x, rooms_y
ROOM = 5.0


def synth(name: str, levels: int, nx: int, ny: int) -> Project:
    p = new_project(name)
    p.levels = [Level(id=f"lvl_{i}", name=f"L{i}", elevation=3.0 * i, height=3.0) for i in range(levels)]
    els = []
    for li in range(levels):
        L = f"lvl_{li}"
        W, H = nx * ROOM, ny * ROOM
        for ix in range(nx + 1):          # walls along Y
            for iy in range(ny):
                wid = f"{L}_vx{ix}_{iy}"
                els.append(Wall(id=wid, level_id=L, a=(ix * ROOM, iy * ROOM), b=(ix * ROOM, (iy + 1) * ROOM), thickness=0.2))
                if ix in (0, nx) or iy % 2 == 0:
                    els.append(Door(id=f"{wid}_d", level_id=L, wall_id=wid, offset=ROOM / 2)) if ix not in (0, nx) else \
                        els.append(Window(id=f"{wid}_w", level_id=L, wall_id=wid, offset=ROOM / 2))
        for iy in range(ny + 1):          # walls along X
            for ix in range(nx):
                wid = f"{L}_hy{iy}_{ix}"
                els.append(Wall(id=wid, level_id=L, a=(ix * ROOM, iy * ROOM), b=((ix + 1) * ROOM, iy * ROOM), thickness=0.2))
                els.append(Window(id=f"{wid}_w", level_id=L, wall_id=wid, offset=ROOM / 2) if iy in (0, ny)
                           else Door(id=f"{wid}_d", level_id=L, wall_id=wid, offset=ROOM / 2))
        els.append(Floor(id=f"{L}_floor", level_id=L, polygon=[(0, 0), (W, 0), (W, H), (0, H)], thickness=0.2))
        for ix in range(nx + 1):
            for iy in range(ny + 1):
                els.append(Column(id=f"{L}_c{ix}_{iy}", level_id=L, pos=(ix * ROOM, iy * ROOM), shape="round", width=0.3))
    top = f"lvl_{levels - 1}"
    els.append(Roof(id="roof", level_id=top, kind="hip", polygon=[(0, 0), (nx * ROOM, 0), (nx * ROOM, ny * ROOM), (0, ny * ROOM)]))
    p.elements = els
    return Project.model_validate(p.model_dump())


def blender_procs() -> list[int]:
    """PIDs of real worker processes: the script must be an actual argv entry (not text inside a shell string)."""
    me = {psutil.Process().pid, *[a.pid for a in psutil.Process().parents()]}
    out = []
    for c in psutil.process_iter(["pid", "cmdline"]):
        argv = c.info["cmdline"] or []
        if c.info["pid"] not in me and any(a.endswith("blender_scripts/worker.py") for a in argv[:4]):
            out.append(c.info["pid"])
    return out


def run(sizes: list[str], repeat: int, tmp: Path) -> dict:
    s = Settings(data_dir=tmp)
    store = ProjectStore(s)
    bs = BuildService(store, s)
    out: dict = {"machine": {"ram_total_mb": round(psutil.virtual_memory().total / 2**20), "cpus": psutil.cpu_count()}, "runs": []}
    me = psutil.Process()
    for size in sizes:
        lv, nx, ny = SIZES[size]
        p = synth(size, lv, nx, ny)
        store.save(p)
        proj_kb = round(store.file(p.id).stat().st_size / 1024, 1)
        for i in range(repeat):
            force = i == 0
            with measure(f"{size}#{i}", include_children=True) as m:
                r = bs.run(f"{size}{i:02d}00000000", p.id, "build", {"force": force}, threading.Event())
            rec = {"size": size, "run": i, "elements": len(p.elements), "levels": lv, "project_json_kb": proj_kb,
                   "seconds": round(m.seconds, 2), "ram_before_mb": round(m.rss_before_mb), "ram_peak_mb": round(m.rss_peak_mb),
                   "ram_after_mb": round(m.rss_after_mb), "py_peak_mb": round(m.py_peak_mb, 1),
                   "blender_peak_mb": r["blender"]["peak_rss_mb"], "blender_seconds": r["blender"]["seconds"],
                   "geometry_s": r["geometry"]["seconds"], "geometry_peak_mb": r["geometry"]["memory"]["rss_peak_mb"],
                   "rebuilt": r["geometry"]["rebuilt"], "cached": r["geometry"]["cached"],
                   "tris_visual": r["triangles"]["visual"], "tris_collision": r["triangles"]["collision"],
                   "objects": r["blender"]["report"]["objects"], "glb_kb": round(r["validation"]["files"][0]["bytes"] / 1024, 1),
                   "leftover_blender_procs": blender_procs()}
            out["runs"].append(rec)
            print(json.dumps(rec), flush=True)
        # incremental edit: change one window, measure rebuild count
        w = next(e for e in p.elements if e.type == "window")
        w.width += 0.1
        p = Project.model_validate(p.model_dump())
        store.save(p)
        with measure(f"{size}-edit") as m:
            r = bs.run(f"{size}edit0000000", p.id, "geometry", {}, threading.Event())
        e = {"size": size, "edit_one_window": {"rebuilt": r["geometry"]["rebuilt"], "cached": r["geometry"]["cached"],
                                               "geometry_s": r["geometry"]["seconds"]}}
        out["runs"].append(e)
        print(json.dumps(e), flush=True)
    out["process_rss_end_mb"] = round(me.memory_info().rss / 2**20)
    out["children_end"] = [c.pid for c in me.children(recursive=True)]
    store.close()
    return out


if __name__ == "__main__":
    import tempfile
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="small,medium,large")
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--out", default=str(ROOT / "docs" / "perf.json"))
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as td:
        res = run(a.sizes.split(","), a.repeat, Path(td))
    Path(a.out).write_text(json.dumps(res, indent=1))
    print("written", a.out)
