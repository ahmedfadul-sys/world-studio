import io, json, struct, zipfile
from app.schemas import Project, Level, LinearFeature
from app import glb as G, levels as L, savefile


def _doc(data):
    n = struct.unpack("<I", data[12:16])[0]
    return json.loads(data[20:20 + n])


def _proj():
    p = Project()
    p.world.size_x_m = 2000; p.world.size_y_m = 2000
    return p


def test_region_glb_is_shifted_and_sized():
    p = _proj()
    data, _ = G.build_glb(p, 65, 256, region=(500, 500, 1500, 1000))
    d = _doc(data)
    assert d["asset"]["extras"]["world_size_m"] == [1000, 500]
    acc = d["accessors"][0]
    assert acc["min"][0] == 0 and abs(acc["max"][0] - 1000) < 1e-3


def test_levels_zip_structure(tmp_path):
    p = _proj()
    p.levels = [Level(id="a", x_m=0, y_m=0, w_m=1000, h_m=1000), Level(id="b", x_m=1000, y_m=0, w_m=1000, h_m=1000)]
    out = tmp_path / "w.zip"
    L.export_levels(p, str(out), 65, 256)
    names = set(zipfile.ZipFile(out).namelist())
    for k in ("Level1", "Level2"):
        for f in (f"{k}.tscn", "terrain.glb", "level.gd", "level.json"):
            assert f"World_Game/{k}/{f}" in names
    t = zipfile.ZipFile(out).read("World_Game/Level1/Level1.tscn").decode()
    assert 'path="res://World_Game/Level1/terrain.glb"' in t and "[node name=\"Level1\" type=\"Node3D\"]" in t


def test_levels_out_of_bounds_rejected():
    p = _proj(); p.levels = [Level(id="a", x_m=1500, y_m=0, w_m=1000, h_m=1000)]
    assert L.validate_levels(p)


def test_river_water_mesh_present():
    p = _proj()
    p.lines.append(LinearFeature(id="r1", kind="river", points=[(100, 1000), (1000, 1100), (1900, 1000)], width_m=20, depth_m=3))
    data, _ = G.build_glb(p, 65, 256)
    assert "Rivers" in [m["name"] for m in _doc(data)["meshes"]]


def test_save_grant_single_use(tmp_path, monkeypatch):
    monkeypatch.setattr(savefile, "_dialog", lambda n, e: str(tmp_path / n))
    pk = savefile.pick("x.glb")
    assert savefile.write(pk["token"], b"abc").read_bytes() == b"abc"
    try:
        savefile.write(pk["token"], b"z"); assert False
    except KeyError:
        pass


def test_polygon_level_clips_triangles():
    p = _proj()
    tri = [(0, 0), (1000, 0), (0, 1000)]                       # مثلث: نصف المربع
    full, rf = G.build_glb(p, 65, 256, region=(0, 0, 1000, 1000))
    cut, rc = G.build_glb(p, 65, 256, region=(0, 0, 1000, 1000), clip_poly=tri)
    assert 0.4 < rc["triangles"] / rf["triangles"] < 0.6
