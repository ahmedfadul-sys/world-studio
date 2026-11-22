"""Phase 1 probe: verify debim's real API by resolving a tiny manifest.

Run:  .venv/bin/python -I tools/phase1_probe_debim.py
Everything printed here is observed output, not assumption.
"""
from __future__ import annotations

import time
import tracemalloc

import psutil

proc = psutil.Process()
rss0 = proc.memory_info().rss / 2**20
tracemalloc.start()
t0 = time.perf_counter()

import debim  # noqa: E402
from debim.schema import ProjectManifest  # noqa: E402
from debim.resolver import SpatialResolver  # noqa: E402

MANIFEST = {
    "project": {"id": "probe", "name": "Probe room"},
    "spatial_structure": {
        "storeys": [{"id": "L0", "name": "Ground", "elevation": 0.0, "height": 3.0}]
    },
    "grids": {"axes_x": {"1": 0.0, "2": 6.0}, "axes_y": {"A": 0.0, "B": 4.0}},
    "materials": [
        {"id": "brick", "name": "Brick", "category": "masonry", "unit_cost_ref": "x"},
        {"id": "conc", "name": "Concrete", "category": "concrete", "unit_cost_ref": "x"},
    ],
    "elements": [
        {
            "class": "IfcWall", "tag": "W1", "material": "brick",
            "thickness": 0.2, "height": 3.0,
            "placement": {"from_grid": ["1", "A"], "to_grid": ["2", "A"], "storey": "L0"},
            "children": [
                {"class": "IfcDoor", "tag": "D1", "offset_distance": 2.0,
                 "dimensions": {"width": 1.0, "height": 2.1}},
                {"class": "IfcWindow", "tag": "WN1", "offset_distance": 4.5,
                 "sill_height": 0.9, "dimensions": {"width": 1.2, "height": 1.2}},
            ],
        },
        {
            "class": "IfcWall", "tag": "W2", "material": "brick",
            "thickness": 0.2, "height": 3.0,
            "placement": {"from_grid": ["2", "A"], "to_grid": ["2", "B"], "storey": "L0"},
        },
        {
            "class": "IfcSlab", "tag": "S1", "material": "conc", "thickness": 0.2,
            "placement": {"boundary": [["1", "A"], ["2", "A"], ["2", "B"], ["1", "B"]],
                          "storey": "L0"},
        },
        {
            "class": "IfcColumn", "tag": "C1", "material": "conc",
            "profile": {"shape": "BOX", "width": 0.3, "depth": 0.3},
            "placement": {"grid": ["1", "B"], "base_storey": "L0", "height": 3.0},
        },
    ],
}

manifest = ProjectManifest.model_validate(MANIFEST)
resolved = SpatialResolver(manifest).resolve()
dt = time.perf_counter() - t0
cur, peak = tracemalloc.get_traced_memory()
rss1 = proc.memory_info().rss / 2**20

print("debim version:", debim.__version__)
print(f"walls={len(resolved.walls)} slabs={len(resolved.slabs)} columns={len(resolved.columns)}")
for w in resolved.walls:
    print(f"  wall {w.tag}: {w.start_point} -> {w.end_point} "
          f"len={w.length:.2f} thk={w.thickness} h={w.height} children={len(w.children)}")
    for c in w.children:
        print(f"    child {type(c).__name__} {c.tag}: pos={c.position} "
              f"w={c.width} h={c.height} sill={c.sill_height}")
for s in resolved.slabs:
    print(f"  slab {s.tag}: poly={s.polygon} thk={s.thickness} area={s.area}")
for c in resolved.columns:
    print(f"  column {c.tag}: {c.start_point} -> {c.end_point} h={c.height}")
print(f"time={dt:.2f}s  RSS {rss0:.0f}->{rss1:.0f} MB  tracemalloc cur={cur/2**20:.1f} peak={peak/2**20:.1f} MB")
