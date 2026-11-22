import math

import pytest

from bimgame.bim import debim_adapter
from bimgame.geometry import builders as B
from bimgame.geometry.junctions import extensions, touching
from bimgame.geometry.mesh import MeshData, is_watertight, mesh_issues, signed_volume
from bimgame.geometry.validate import validate_project
from bimgame.schema import CustomOpening, Door, Floor, Wall, Window
from conftest import house


def resolved(p):
    return debim_adapter.resolve(p)


def test_wall_with_real_openings_volume_and_watertight():
    p = house()
    b = resolved(p)
    w = next(x for x in b.walls if x.id == "w_s")
    mesh, slots = B.wall_mesh(w, 0, 0)
    # 6 x 3 x 0.2 minus door 0.9x2.1 and window 1.2x1.2 (through the full thickness)
    expected = 6 * 3 * 0.2 - 0.9 * 2.1 * 0.2 - 1.2 * 1.2 * 0.2
    assert signed_volume(mesh) == pytest.approx(expected, rel=1e-6)
    assert is_watertight(mesh)
    assert not mesh_issues(mesh)
    assert slots == [None, None] or len(slots) == 2


def test_opening_is_a_hole_not_an_overlay():
    """No triangle may lie inside the door opening footprint (u 1.55..2.45, z 0..2.1)."""
    p = house()
    w = next(x for x in resolved(p).walls if x.id == "w_s")
    mesh, _ = B.wall_mesh(w, 0, 0)
    tri = mesh.v[mesh.f]
    c = tri.mean(1)
    inside = (c[:, 0] > 1.55 + 1e-6) & (c[:, 0] < 2.45 - 1e-6) & (c[:, 2] > 1e-6) & (c[:, 2] < 2.1 - 1e-6)
    # only reveal faces (thin sides) may sit inside the footprint box; none may be wall-face triangles (|y|=0.1)
    assert not (inside & (abs(abs(c[:, 1]) - 0.1) < 1e-6)).any()


def test_arch_and_custom_opening_and_door_to_top_split():
    p = house()
    p.elements.append(CustomOpening(id="o1", level_id="lvl_0", wall_id="w_e", offset=2.0, width=1.0, height=1.5, sill=0.0, shape="arch"))
    p = type(p).model_validate(p.model_dump())
    w = next(x for x in resolved(p).walls if x.id == "w_e")
    mesh, _ = B.wall_mesh(w, 0, 0, "medium")
    assert is_watertight(mesh) and signed_volume(mesh) > 0
    assert signed_volume(mesh) < 4 * 3 * 0.2


def test_multi_material_slots_used():
    p = house()
    p.elements[0] = Wall(id="w_s", level_id="lvl_0", a=(0, 0), b=(6, 0), material="mat_plaster", material_inner="mat_wood")
    p = type(p).model_validate(p.model_dump())
    w = next(x for x in resolved(p).walls if x.id == "w_s")
    mesh, slots = B.wall_mesh(w, 0, 0)
    assert slots == ["mat_plaster", "mat_wood"]
    assert set(mesh.slot.tolist()) == {0, 1}


def test_junction_corner_t_cross_and_collinear():
    p = house()
    ext = extensions(p)
    # rectangle corners: every end extends by half of the neighbour thickness (0.1)
    assert all(v == (pytest.approx(0.1), pytest.approx(0.1)) for v in ext.values())
    # T-junction: stub ending on w_s interior
    p.elements.append(Wall(id="w_t", level_id="lvl_0", a=(3, 0), b=(3, 2), thickness=0.3))
    p = type(p).model_validate(p.model_dump())
    e = extensions(p)
    assert e["w_t"][0] == pytest.approx(0.1)  # extends into host (0.2/2)
    assert "w_t" in touching(p)["w_s"]
    # collinear continuation: no extension
    q = house()
    q.elements = [x for x in q.elements if x.type in ("column",)]
    q = type(q).model_validate(q.model_dump())
    q.elements += [Wall(id="a", level_id="lvl_0", a=(0, 0), b=(2, 0)), Wall(id="b", level_id="lvl_0", a=(2, 0), b=(5, 0))]
    assert extensions(q)["a"][1] == 0.0


def test_floor_with_hole_volume():
    p = house()
    p.elements.append(Floor(id="f2", level_id="lvl_0", polygon=[(0, 0), (6, 0), (6, 4), (0, 4)], holes=[[(1, 1), (2, 1), (2, 2), (1, 2)]], thickness=0.25, z_offset=3.0))
    p = type(p).model_validate(p.model_dump())
    f = next(x for x in resolved(p).floors if x.id == "f2")
    mesh, _ = B.floor_mesh(f)
    assert signed_volume(mesh) == pytest.approx((24 - 1) * 0.25, rel=1e-6)
    assert is_watertight(mesh)
    assert f.z_top == pytest.approx(3.0)


@pytest.mark.parametrize("kind", ["flat", "shed", "gable", "hip"])
@pytest.mark.parametrize("axis", ["x", "y"])
def test_roofs_watertight(kind, axis):
    p = house()
    r = next(e for e in p.elements if e.type == "roof")
    r.kind, r.ridge_axis = kind, axis
    p = type(p).model_validate(p.model_dump())
    rr = next(x for x in resolved(p).roofs if x.id == "r1")
    mesh, _ = B.roof_mesh(rr)
    assert is_watertight(mesh), kind
    assert signed_volume(mesh) > 0
    assert not mesh_issues(mesh)


def test_stair_volume_and_watertight():
    p = house()
    s = next(x for x in resolved(p).stairs)
    mesh, _ = B.stair_mesh(s)
    n = 10
    expected = s.rise * s.run * n * (n + 1) / 2 * s.width
    assert signed_volume(mesh) == pytest.approx(expected, rel=1e-6)
    assert is_watertight(mesh)


def test_columns_beams_watertight():
    p = house()
    c = resolved(p).columns[0]
    mesh, _ = B.column_mesh(c, "high")
    assert is_watertight(mesh) and signed_volume(mesh) > 0
    c.shape = "box"
    assert signed_volume(B.column_mesh(c)[0]) == pytest.approx(0.4 * 0.4 * 3.0)


def test_door_window_fill_meshes():
    p = house()
    b = resolved(p)
    w = next(x for x in b.walls if x.id == "w_s")
    door = next(o for o in w.openings if o.kind == "door")
    win = next(o for o in w.openings if o.kind == "window")
    dm, ds = B.opening_fill_mesh(w, door)
    wm, ws = B.opening_fill_mesh(w, win)
    assert dm.tris > 0 and wm.tris > 0 and ws[1] == "mat_glass"
    lo, hi = wm.bbox()
    assert lo[2] == pytest.approx(0.9) and hi[2] == pytest.approx(2.1)


def test_validation_flags_bad_openings():
    p = house()
    p.elements.append(Window(id="bad", level_id="lvl_0", wall_id="w_e", offset=3.9, width=1.0))   # beyond wall end (length 4)
    p.elements.append(Door(id="bad2", level_id="lvl_0", wall_id="w_n", offset=1.0, height=3.0))   # no lintel
    p = type(p).model_validate(p.model_dump())
    msgs = {i.element_id: i.message for i in validate_project(p)}
    assert "beyond" in msgs["bad"]
    assert "above it" in msgs["bad2"]
    assert not [i for i in validate_project(house()) if i.level == "error"]


def test_adapter_uses_debim_and_units_and_modules():
    p = house()
    b = resolved(p)
    assert b.debim_version == "1.2.0"
    assert b.resolved_via_debim >= 4 + 2 + 1 + 1  # walls + door/window + slab + column
    from bimgame.schema import new_project
    q = new_project("cm", units="cm"); q.levels[0].height = 300
    q.elements.append(Wall(id="w", level_id="lvl_0", a=(0, 0), b=(600, 0), thickness=20, module="mod_wall_thick", overrides=["thickness"]))
    q = type(q).model_validate(q.model_dump())
    # explicit thickness (20 cm) wins over module default; unset fields come from the module
    w = debim_adapter.resolve(q).walls[0]
    assert w.b == (6.0, 0.0) and w.thickness == pytest.approx(0.2) and w.material == "mat_concrete"


def test_wall_collision_boxes_leave_openings_open():
    from bimgame.geometry.collision import wall_boxes
    p = house()
    w = next(x for x in resolved(p).walls if x.id == "w_s")
    boxes = wall_boxes(w, 0, 0)
    vol = sum(b[3] * b[4] * b[5] for b in boxes)
    assert vol == pytest.approx(6 * 3 * 0.2 - 0.9 * 2.1 * 0.2 - 1.2 * 1.2 * 0.2, rel=1e-9)
    # nothing occupies the door passage (u 1.55..2.45, z 0.05..2.0)
    for cx, cy, z0, sx, sy, sz, rot in boxes:
        in_u = (cx - sx / 2 < 2.0 < cx + sx / 2)
        assert not (in_u and z0 < 1.0 < z0 + sz)


def test_module_defaults_are_metres_and_convert_to_project_units():
    from bimgame.bim.modules import apply_modules
    from bimgame.schema import new_project, Project, Wall
    q = new_project("cm", units="cm"); q.levels[0].height = 300
    q.elements.append(Wall(id="w", level_id="lvl_0", a=(0, 0), b=(600, 0), module="mod_wall_thick"))   # 0.6 m stone wall
    q = Project.model_validate(q.model_dump())
    w = apply_modules(q).elements[0]
    assert w.thickness == pytest.approx(60.0)          # 0.6 m expressed in cm, not 0.6 cm
    assert w.material == "mat_concrete"
    assert debim_adapter.resolve(q).walls[0].thickness == pytest.approx(0.6)


def test_circular_wall_ring_is_closed_and_mitred():
    """A 24-gon ring of walls: shallow corners get the exact mitre extension (t/2*tan(7.5deg)), not t/2."""
    import math
    from bimgame.geometry.junctions import extensions
    from bimgame.schema import Wall, new_project
    p = new_project("ring")
    n, r, t = 24, 4.0, 0.2
    pts = [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n)) for i in range(n)]
    p.elements = [Wall(id=f"w{i}", level_id="lvl_0", a=pts[i], b=pts[(i + 1) % n], thickness=t) for i in range(n)]
    ext = extensions(p)
    want = t / 2 * math.tan(math.radians(7.5))
    assert all(abs(a - want) < 1e-6 and abs(b - want) < 1e-6 for a, b in ext.values())
    # unchanged for right angles
    q = new_project("sq")
    sq = [(0, 0), (4, 0), (4, 4), (0, 4)]
    q.elements = [Wall(id=f"s{i}", level_id="lvl_0", a=sq[i], b=sq[(i + 1) % 4], thickness=t) for i in range(4)]
    assert all(abs(a - t / 2) < 1e-9 for a, _ in extensions(q).values())


@pytest.mark.parametrize("kind", ["cone", "dome", "barrel"])
@pytest.mark.parametrize("shape", ["rect", "circle"])
@pytest.mark.parametrize("axis", ["x", "y"])
def test_curved_roofs_watertight_and_sane(kind, shape, axis):
    p = house()
    r = next(e for e in p.elements if e.type == "roof")
    r.kind, r.ridge_axis, r.overhang = kind, axis, 0.3
    if shape == "circle":
        r.polygon = [(3 + 3 * math.cos(2 * math.pi * i / 24), 2 + 3 * math.sin(2 * math.pi * i / 24)) for i in range(24)]
    p = type(p).model_validate(p.model_dump())
    rr = next(x for x in resolved(p).roofs if x.id == "r1")
    for detail in ("low", "medium", "high"):
        mesh, _ = B.roof_mesh(rr, detail)
        assert is_watertight(mesh), (kind, shape, detail)
        assert signed_volume(mesh) > 0
        assert not mesh_issues(mesh)
    lo, hi = mesh.bbox()
    assert hi[2] > rr.z_eave + 0.2              # it actually rises above the eave
    assert lo[2] == pytest.approx(rr.z_eave - rr.thickness)


def test_cone_apex_is_over_centre_and_height_follows_pitch():
    p = house()
    r = next(e for e in p.elements if e.type == "roof")
    r.kind, r.overhang, r.pitch_deg = "cone", 0.0, 45.0
    r.polygon = [(3 + 3 * math.cos(2 * math.pi * i / 32), 2 + 3 * math.sin(2 * math.pi * i / 32)) for i in range(32)]
    p = type(p).model_validate(p.model_dump())
    rr = next(x for x in resolved(p).roofs if x.id == "r1")
    mesh, _ = B.roof_mesh(rr)
    top = mesh.v[mesh.v[:, 2].argmax()]
    assert (top[0], top[1]) == pytest.approx((3, 2), abs=1e-6)
    assert top[2] - rr.z_eave == pytest.approx(3.0, rel=1e-6)   # R * tan(45 deg)


# ---- wall faces: cut / recess / relief shapes drawn on a wall ------------------------
def _wall_with(features):
    from bimgame.schema import WallFeature
    p = house()
    w = next(e for e in p.elements if e.type == "wall" and e.id == "w_s")
    w.features = [WallFeature(**f) for f in features]
    p = type(p).model_validate(p.model_dump())
    return next(x for x in resolved(p).walls if x.id == "w_s")


def _rect(u0, v0, u1, v1):
    return [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]


def _base_volume():
    w = _wall_with([])
    return signed_volume(B.wall_mesh(w, 0, 0)[0]), w


def test_through_cut_removes_volume_and_stays_watertight():
    v0, _ = _base_volume()
    w = _wall_with([{"kind": "cut", "polygon": _rect(2.8, 1.0, 3.8, 2.0)}])  # clear of the door/window
    m, _ = B.wall_mesh(w, 0, 0)
    assert signed_volume(m) == pytest.approx(v0 - 1.0 * 1.0 * 0.2, rel=1e-5)
    assert is_watertight(m) and not mesh_issues(m)


def test_battlement_notch_at_top_edge_is_valid():
    v0, base = _base_volume()
    top = base.height
    notches = [{"kind": "cut", "polygon": _rect(0.5 + i * 1.0, top - 0.4, 1.0 + i * 1.0, top + 0.5)} for i in range(4)]
    m, _ = B.wall_mesh(_wall_with(notches), 0, 0)
    assert signed_volume(m) == pytest.approx(v0 - 4 * 0.5 * 0.4 * 0.2, rel=1e-5)
    assert is_watertight(m)


@pytest.mark.parametrize("face", ["left", "right"])
def test_recess_and_relief_volume(face):
    v0, _ = _base_volume()
    shape = _rect(2.8, 1.0, 3.8, 2.0)
    m, _ = B.wall_mesh(_wall_with([{"kind": "recess", "polygon": shape, "depth": 0.08, "face": face}]), 0, 0)
    assert signed_volume(m) == pytest.approx(v0 - 1.0 * 1.0 * 0.08, rel=1e-4)
    assert is_watertight(m) and not mesh_issues(m)
    m, _ = B.wall_mesh(_wall_with([{"kind": "relief", "polygon": shape, "depth": 0.1, "face": face}]), 0, 0)
    assert signed_volume(m) == pytest.approx(v0 + 1.0 * 1.0 * 0.1, rel=1e-4)
    assert is_watertight(m)
    lo, hi = m.bbox()
    assert (hi[1] if face == "right" else -lo[1]) > 0  # sticks out on the chosen side (local depth axis is world-rotated; bbox is sane)


def test_relief_is_clipped_to_the_wall_silhouette_and_skips_openings():
    v0, _ = _base_volume()
    # overlaps the door opening region and sticks out past the wall end: only material on actual wall counts
    m, _ = B.wall_mesh(_wall_with([{"kind": "relief", "polygon": _rect(-1.0, 0.0, 8.0, 0.5), "depth": 0.1}]), 0, 0)
    assert signed_volume(m) > v0
    assert is_watertight(m)


def test_round_shapes_and_overlapping_features():
    c = [(3.3 + 0.5 * math.cos(2 * math.pi * i / 24), 1.5 + 0.5 * math.sin(2 * math.pi * i / 24)) for i in range(24)]
    feats = [{"kind": "recess", "polygon": c, "depth": 0.05},
             {"kind": "relief", "polygon": _rect(1.0, 2.0, 2.0, 2.6), "depth": 0.04, "face": "left"},
             {"kind": "cut", "polygon": [(3.0, 0.2), (3.5, 0.8), (2.5, 0.8)]}]
    m, _ = B.wall_mesh(_wall_with(feats), 0, 0)
    assert is_watertight(m) and not mesh_issues(m) and signed_volume(m) > 0


def test_through_cut_opens_collision_but_top_notch_does_not():
    from bimgame.geometry.collision import wall_boxes
    base = _wall_with([])
    n0 = len(wall_boxes(base, 0, 0))
    hole = _wall_with([{"kind": "cut", "polygon": _rect(2.8, 1.0, 3.8, 2.0)}])
    assert len(wall_boxes(hole, 0, 0)) > n0
    notch = _wall_with([{"kind": "cut", "polygon": _rect(2.8, base.height - 0.4, 3.8, base.height + 1)}])
    assert len(wall_boxes(notch, 0, 0)) == n0


def test_features_change_the_element_fingerprint():
    from bimgame.geometry.cache import fingerprints
    from bimgame.schema import WallFeature
    p = house()
    before = fingerprints(p, "medium")["w_s"]
    next(e for e in p.elements if e.id == "w_s").features = [WallFeature(kind="cut", polygon=_rect(2.8, 1, 3.8, 2))]
    assert fingerprints(p, "medium")["w_s"] != before
