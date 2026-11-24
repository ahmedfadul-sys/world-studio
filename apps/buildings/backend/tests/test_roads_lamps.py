import json
import math
import struct

import pytest

from bimgame.bim import debim_adapter
from bimgame.geometry import builders as B
from bimgame.geometry.cache import build_geometry, load_manifest
from bimgame.schema import Guide, Lamp, Road, Stair, new_project, surface_material_id, with_surface_materials
from bimgame.services.preview_glb import write_preview_glb
from conftest import house


def _proj():
    p = house()
    return p


def test_road_mesh_has_road_and_sidewalk_and_right_area():
    p = _proj()
    lvl = p.levels[0].id
    p.elements.append(Road(id="r1", level_id=lvl, path=[(-20, -10), (30, -10)], width=6, sidewalk=2, surface="dirt"))
    r = debim_adapter.resolve(p, element_ids={"r1"}).roads[0]
    mesh, slots = B.road_mesh(r)
    assert slots[0] == surface_material_id("dirt") and slots[1] == surface_material_id("sidewalk")
    assert set(mesh.slot.tolist()) == {0, 1}
    # أعلى نقطة = سماكة الطريق + ارتفاع الرصيف
    assert mesh.v[:, 2].max() == pytest.approx(0.1 + 0.15)
    # مساحة سطح الطريق 50 x 6
    top = mesh.f[(mesh.slot == 0)]
    a, b, c = (mesh.v[top[:, i]] for i in range(3))
    import numpy as np
    n = np.cross(b - a, c - a)
    up = n[:, 2] > 0
    assert (np.linalg.norm(n, axis=1)[up] / 2).sum() == pytest.approx(300, rel=1e-6)


def test_road_bend_and_no_sidewalk():
    p = _proj()
    p.elements.append(Road(id="r2", level_id=p.levels[0].id, path=[(0, 0), (20, 0), (20, 20)], width=4, sidewalk=0))
    r = debim_adapter.resolve(p, element_ids={"r2"}).roads[0]
    mesh, slots = B.road_mesh(r)
    assert set(mesh.slot.tolist()) == {0}


def test_spiral_stair_height_and_radius():
    p = _proj()
    p.elements.append(Stair(id="sp", level_id=p.levels[0].id, start=(2, 2), kind="spiral", width=1.0, inner_radius=0.3,
                            steps=20, rise=0.15, turn_deg=360))
    s = debim_adapter.resolve(p, element_ids={"sp"}).stairs[0]
    mesh, _ = B.stair_mesh(s)
    assert mesh.v[:, 2].max() >= 20 * 0.15
    r = ((mesh.v[:, 0] - 2) ** 2 + (mesh.v[:, 1] - 2) ** 2) ** 0.5
    assert r.max() == pytest.approx(1.3, abs=1e-6)


def test_lamp_light_and_preview_glb(tmp_path):
    p = _proj()
    lvl = p.levels[0].id
    p.elements.append(Lamp(id="l1", level_id=lvl, pos=(1, 1), height=5, arm=1.0, arm_deg=0, intensity=500))
    p.elements.append(Road(id="r1", level_id=lvl, path=[(-5, -4), (15, -4)]))
    gdir = tmp_path / "g"
    build_geometry(p, gdir)
    parts = load_manifest(gdir)["parts"]
    assert parts["l1"]["light"]["intensity"] == 500
    assert parts["l1"]["light"]["pos"][2] == pytest.approx(4.85)
    out = tmp_path / "p.glb"
    write_preview_glb(parts, gdir, [m.model_dump() for m in with_surface_materials(p.materials)], out)
    raw = out.read_bytes()
    n = struct.unpack("<I", raw[12:16])[0]
    doc = json.loads(raw[20:20 + n])
    assert doc["extensions"]["KHR_lights_punctual"]["lights"][0]["intensity"] == 500
    assert "KHR_lights_punctual" in doc["extensionsUsed"]


def test_guides_never_reach_geometry(tmp_path):
    p = _proj()
    base = build_geometry(p, tmp_path / "a")
    p2 = p.model_copy(deep=True)
    p2.guides.append(Guide(kind="grid"))
    again = build_geometry(p2, tmp_path / "a")
    assert not again.rebuilt                      # لا تغيير في أي عنصر
    assert set(load_manifest(tmp_path / "a")["parts"]) == set(load_manifest(tmp_path / "a")["parts"])
    assert not [k for k in load_manifest(tmp_path / "a")["parts"] if k.startswith("gd")]
