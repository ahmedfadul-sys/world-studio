"""Generate examples/demo_house.json: a two-storey house (hip-less gable roof, stair, balcony).

  .venv/bin/python -I tools/make_demo.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from bimgame.schema import (Column, Door, Floor, Level, Roof, Stair, Wall, Window, new_project)  # noqa: E402

p = new_project("Demo house")
p.levels = [Level(id="lvl_0", name="Ground", elevation=0.0, height=3.0),
            Level(id="lvl_1", name="First", elevation=3.0, height=3.0)]
W, D = 10.0, 7.0
pts = [(0, 0), (W, 0), (W, D), (0, D)]
els = []
for lv in ("lvl_0", "lvl_1"):
    for i in range(4):
        els.append(Wall(id=f"{lv}_w{i}", level_id=lv, a=pts[i], b=pts[(i + 1) % 4], thickness=0.25))
    els.append(Floor(id=f"{lv}_floor", level_id=lv, polygon=pts, thickness=0.2))
els.append(Wall(id="lvl_0_div", level_id="lvl_0", a=(5, 0), b=(5, D), thickness=0.15))
els.append(Door(id="front_door", level_id="lvl_0", wall_id="lvl_0_w0", offset=2.5, width=1.0, height=2.2))
els.append(Door(id="inner_door", level_id="lvl_0", wall_id="lvl_0_div", offset=3.5, width=0.9, height=2.1))
els.append(Window(id="win_a", level_id="lvl_0", wall_id="lvl_0_w0", offset=7.5, width=1.4, height=1.2, sill=0.9))
els.append(Window(id="win_b", level_id="lvl_0", wall_id="lvl_0_w1", offset=3.5, width=1.6, height=1.2, sill=0.9))
els.append(Window(id="win_c", level_id="lvl_1", wall_id="lvl_1_w0", offset=5.0, width=2.0, height=1.2, sill=0.9))
els.append(Window(id="win_d", level_id="lvl_1", wall_id="lvl_1_w2", offset=5.0, width=1.4, height=1.2, sill=0.9))
els.append(Column(id="col_porch", level_id="lvl_0", pos=(0.4, -0.0), shape="round", width=0.3))
els.append(Roof(id="roof", level_id="lvl_1", kind="gable", polygon=pts, pitch_deg=30.0))
p.elements = els
out = ROOT / "examples" / "demo_house.json"
out.parent.mkdir(exist_ok=True)
out.write_text(p.model_dump_json(indent=1))
print("wrote", out, len(els), "elements")
