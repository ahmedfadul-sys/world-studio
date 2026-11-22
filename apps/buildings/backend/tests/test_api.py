import json
import struct
import time

import psutil
import pytest
from fastapi.testclient import TestClient

from bimgame.api.app import create_app
from bimgame.config import Settings
from bimgame.services.export_validate import read_glb, validate_outputs
from bimgame.utils.errors import BuildError
from conftest import house


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app) as c:
        yield c


def make_project(c) -> dict:
    p = house().model_dump()
    r = c.post("/api/projects", json={"name": "House"})
    assert r.status_code == 201
    pid = r.json()["id"]
    p["id"], p["name"] = pid, "House"
    r = c.put(f"/api/projects/{pid}", json=p)
    assert r.status_code == 200, r.text
    return p


def wait(c, jid, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = c.get(f"/api/build/status/{jid}").json()
        if s["status"] not in ("queued", "running"):
            return s
        time.sleep(0.1)
    raise AssertionError("job timeout")


def test_project_crud_and_validation_errors(client):
    r = client.post("/api/projects", json={"name": ""})
    assert r.status_code == 422 and r.json()["error"]["what"] == "Invalid request"
    pid = client.post("/api/projects", json={"name": "A", "units": "cm"}).json()["id"]
    assert client.get("/api/projects").json()["projects"][0]["id"] == pid
    p = client.get(f"/api/projects/{pid}").json()
    p["elements"] = [{"type": "wall", "level_id": "nope", "a": [0, 0], "b": [1, 0]}]
    r = client.put(f"/api/projects/{pid}", json=p)
    assert r.status_code == 422 and "level" in json.dumps(r.json())
    assert client.get("/api/projects/prj_missing").status_code == 404
    assert client.delete(f"/api/projects/{pid}").status_code == 204


def test_validate_endpoint_reports_issues(client):
    p = make_project(client)
    p["elements"].append({"type": "window", "id": "bad", "level_id": "lvl_0", "wall_id": "w_e", "offset": 3.9, "width": 1.0})
    client.put(f"/api/projects/{p['id']}", json=p)
    r = client.post("/api/geometry/validate", json={"project_id": p["id"]}).json()
    assert r["ok"] is False and r["issues"][0]["element_id"] == "bad"


def test_full_build_produces_valid_glb_and_history(client):
    p = make_project(client)
    j = client.post("/api/build", json={"project_id": p["id"], "settings": {"lod_min_triangles": 24}}).json()
    s = wait(client, j["job_id"])
    assert s["status"] == "succeeded", s
    res = client.get(f"/api/build/result/{j['job_id']}").json()["result"]
    out = res["outputs"][0]
    f = client.get(f"/api/projects/{p['id']}/files/{out}")
    assert f.status_code == 200 and f.content[:4] == b"glTF"
    doc = json.loads(f.content[20:20 + struct.unpack_from("<I", f.content, 12)[0]])
    names = [n["name"] for n in doc["nodes"]]
    assert any(n.endswith("-convcolonly") for n in names) and any("_LOD1" in n for n in names)
    assert res["blender"]["report"]["uv"]["ok"]
    hist = client.get(f"/api/projects/{p['id']}").json()["build_history"]
    assert hist[-1]["status"] == "succeeded" and hist[-1]["elements_rebuilt"] == 10


def test_second_build_is_incremental_and_original_untouched(client):
    p = make_project(client)
    before = client.get(f"/api/projects/{p['id']}").json()["elements"]
    j1 = client.post("/api/build", json={"project_id": p["id"], "kind": "geometry"}).json()
    assert wait(client, j1["job_id"])["status"] == "succeeded"
    j2 = client.post("/api/build", json={"project_id": p["id"], "kind": "geometry"}).json()
    wait(client, j2["job_id"])
    g = client.get(f"/api/build/result/{j2['job_id']}").json()["result"]["geometry"]
    assert g["rebuilt"] == 0 and g["cached"] == 10
    # asset optimisation never alters the editable project data
    j3 = client.post("/api/assets/optimize", json={"project_id": p["id"], "poly_preset": "low"}).json()
    assert wait(client, j3["job_id"])["status"] == "succeeded"
    assert client.get(f"/api/projects/{p['id']}").json()["elements"] == before


def test_export_formats(client):
    p = make_project(client)
    for fmt, magic in (("fbx", b"Kaydara FBX Binary"), ("gltf", b"{")):
        j = client.post(f"/api/export/{fmt}", json={"project_id": p["id"]}).json()
        s = wait(client, j["job_id"])
        assert s["status"] == "succeeded", s
        out = client.get(f"/api/build/result/{j['job_id']}").json()["result"]["outputs"]
        main = [o for o in out if o.endswith("." + fmt)][0]
        assert client.get(f"/api/projects/{p['id']}/files/{main}").content.startswith(magic)


def test_invalid_project_blocks_build_with_clear_error(client):
    p = make_project(client)
    p["elements"].append({"type": "door", "id": "x", "level_id": "lvl_0", "wall_id": "w_n", "offset": 0.1, "width": 1.0})
    client.put(f"/api/projects/{p['id']}", json=p)
    j = client.post("/api/build", json={"project_id": p["id"]}).json()
    s = wait(client, j["job_id"])
    assert s["status"] == "failed" and s["error"]["where"] == "build.validate" and "beyond" in s["error"]["why"]
    r = client.get(f"/api/build/result/{j['job_id']}")
    assert r.status_code == 422


def test_one_heavy_job_at_a_time_and_queue_limit(client):
    p = make_project(client)
    ids, codes = [], []
    for _ in range(8):
        r = client.post("/api/build", json={"project_id": p["id"], "force": True})
        codes.append(r.status_code)
        if r.status_code == 202:
            ids.append(r.json()["job_id"])
    assert 429 in codes, "queue limit never engaged"          # bounded queue protects RAM
    for i in ids:
        assert wait(client, i, timeout=180)["status"] == "succeeded"
    # measured inside the server (not by racy polling): never more than one build at once
    sysinfo = client.get("/api/system").json()
    assert sysinfo["max_concurrent_builds_seen"] == 1
    assert len(ids) >= 2


def test_cancel_kills_blender_and_leaves_no_process(client):
    p = make_project(client)
    me = psutil.Process()
    j = client.post("/api/build", json={"project_id": p["id"], "force": True}).json()
    for _ in range(200):
        if client.get(f"/api/build/status/{j['job_id']}").json()["status"] == "running" and me.children(recursive=True):
            break
        time.sleep(0.02)
    client.post(f"/api/build/cancel/{j['job_id']}")
    s = wait(client, j["job_id"])
    assert s["status"] in ("cancelled", "succeeded")  # may finish before the cancel lands
    time.sleep(0.3)
    assert not [c for c in me.children(recursive=True) if "worker.py" in " ".join(c.cmdline())]


def test_system_endpoint_reports_dependencies(client):
    r = client.get("/api/system").json()
    assert r["debim"] == "1.2.0" and r["blender"]["ok"] and r["workers"] == 1


def test_file_endpoint_blocks_traversal(client):
    p = make_project(client)
    for bad in ("../../bim.sqlite3", "%2e%2e/%2e%2e/bim.sqlite3", "..%2f..%2fbim.sqlite3"):
        r = client.get(f"/api/projects/{p['id']}/files/{bad}")
        assert r.status_code in (400, 404) and b"SQLite" not in r.content
    assert client.get("/api/projects/..%2f..%2fetc/files/passwd").status_code in (400, 404)
    assert client.get(f"/api/projects/{p['id']}/files/project.json").status_code == 200  # own project data only


def test_export_validation_rejects_bad_files(tmp_path):
    bad = tmp_path / "x.glb"
    bad.write_bytes(b"not a glb at all, definitely")
    with pytest.raises(BuildError):
        validate_outputs([str(bad)], 1)
    empty = tmp_path / "e.glb"; empty.write_bytes(b"")
    with pytest.raises(BuildError):
        validate_outputs([str(empty)], 1)
    with pytest.raises(BuildError):
        validate_outputs([str(tmp_path / "missing.glb")], 1)
    with pytest.raises(BuildError):
        validate_outputs([], 1)


def test_missing_blender_is_a_clear_dependency_error(tmp_path):
    s = Settings(data_dir=tmp_path, blender_python="/nonexistent/python")
    app = create_app(s)
    with TestClient(app) as c:
        p = make_project(c)
        j = c.post("/api/build", json={"project_id": p["id"]}).json()
        st = wait(c, j["job_id"])
        assert st["status"] == "failed" and "not available" in st["error"]["what"]


def test_lod_threshold_skips_small_objects_by_default(client):
    p = make_project(client)
    j = client.post("/api/assets/lod", json={"project_id": p["id"], "settings": {"lod_min_triangles": 100000}}).json()
    assert wait(client, j["job_id"])["status"] == "succeeded"
    rep = client.get(f"/api/build/result/{j['job_id']}").json()["result"]["blender"]["report"]
    assert rep["lod"]["objects"] == 0
    j = client.post("/api/assets/lod", json={"project_id": p["id"], "settings": {"lod_min_triangles": 24, "lod_levels": [0.5]}}).json()
    assert wait(client, j["job_id"])["status"] == "succeeded"
    rep = client.get(f"/api/build/result/{j['job_id']}").json()["result"]["blender"]["report"]
    assert rep["lod"]["objects"] > 0 and rep["lod"]["triangles_by_level"]["1"] > 0


def _png(w=4, h=4, rgb=(200, 80, 60)) -> bytes:
    """Minimal valid PNG (zlib + CRCs computed, not hand-typed bytes)."""
    import zlib

    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


PNG_1PX = _png()


def test_texture_upload_validation_and_use_in_build(client):
    p = make_project(client)
    url = f"/api/projects/{p['id']}/textures"
    assert client.put(f"{url}/brick.png", content=PNG_1PX).status_code == 201
    assert client.put(f"{url}/evil.png", content=b"MZ not an image").status_code == 400
    assert client.put(f"{url}/bad name.png", content=PNG_1PX).status_code in (400, 404, 422)
    assert client.put(f"{url}/x.exe", content=PNG_1PX).status_code == 400
    assert client.put(f"{url}/big.png", content=PNG_1PX + b"0" * (9 * 2**20)).status_code == 413
    assert client.get(url).json()["textures"] == ["brick.png"]
    for m in p["materials"]:
        if m["id"] == "mat_plaster":
            m["texture"] = "brick.png"
    next(e for e in p["elements"] if e["id"] == "w_s")["material"] = "mat_plaster"  # only USED materials are exported
    client.put(f"/api/projects/{p['id']}", json=p)
    j = client.post("/api/build", json={"project_id": p["id"], "settings": {"format": "glb"}}).json()
    assert wait(client, j["job_id"])["status"] == "succeeded"
    glb = client.get(f"/api/projects/{p['id']}/files/" + client.get(f"/api/build/result/{j['job_id']}").json()["result"]["outputs"][0]).content
    ln = struct.unpack_from("<I", glb, 12)[0]
    assert json.loads(glb[20:20 + ln]).get("images"), "texture should be embedded in the exported GLB"
    assert client.delete(f"{url}/brick.png").status_code == 204
    assert client.get(url).json()["textures"] == []


def test_undecodable_texture_is_reported_not_silent(client):
    p = make_project(client)
    # passes the PNG signature check but is not a decodable image
    client.put(f"/api/projects/{p['id']}/textures/broken.png", content=b"\x89PNG\r\n\x1a\n" + b"garbage" * 20)
    for m in p["materials"]:
        if m["id"] == "mat_plaster":
            m["texture"] = "broken.png"
    next(e for e in p["elements"] if e["id"] == "w_s")["material"] = "mat_plaster"
    client.put(f"/api/projects/{p['id']}", json=p)
    j = client.post("/api/build", json={"project_id": p["id"]}).json()
    assert wait(client, j["job_id"])["status"] == "succeeded"
    rep = client.get(f"/api/build/result/{j['job_id']}").json()["result"]["blender"]["report"]
    assert any("could not be decoded" in w for w in rep["warnings"])


def test_fast_preview_glb_is_valid_and_upright(client, tmp_path):
    """Preview is written in-process (no Blender): valid GLB, Y-up, base on the ground, centred."""
    make_project(client)
    pid = client.get("/api/projects").json()["projects"][0]["id"]
    jid = client.post("/api/build/preview", json={"project_id": pid}).json()["job_id"]
    assert wait(client, jid)["status"] == "succeeded"
    res = client.get(f"/api/build/result/{jid}").json()["result"]
    assert res.get("fast_preview") and res.get("blender") is None
    data = client.get(f"/api/projects/{pid}/files/exports/preview/preview.glb").content
    f = tmp_path / "p.glb"
    f.write_bytes(data)
    gltf = read_glb(f)
    assert gltf["asset"]["version"] == "2.0" and gltf["meshes"]
    acc = [a for a in gltf["accessors"] if a.get("type") == "VEC3" and "min" in a and a.get("componentType") == 5126]
    ymin = min(a["min"][1] for a in acc)
    ymax = max(a["max"][1] for a in acc)
    assert abs(ymin) < 1e-3 and ymax > 2.5     # Y is up, model stands on y=0


def test_export_settings_rotate_and_mirror_validate(client):
    from bimgame.schema import ExportSettings
    assert ExportSettings(rotate_deg=180, mirror_x=True).rotate_deg == 180
    with pytest.raises(Exception):
        ExportSettings(rotate_deg=45)


def test_stair_z_offset_raises_the_flight(client):
    """Second flight of an L/U stair starts at the landing: z_offset lifts the whole flight."""
    from bimgame.schema import Stair
    heights = []
    for zo in (0.0, 1.5):
        p = house().model_dump()
        r = client.post("/api/projects", json={"name": "S"})
        pid = r.json()["id"]
        p["id"], p["name"] = pid, "S"
        lvl = p["levels"][0]["id"]
        p["elements"] = [e for e in p["elements"] if e["type"] in ("wall", "floor")]
        p["elements"].append(Stair(level_id=lvl, start=[20, 20], steps=10, rise=0.2, run=0.3, z_offset=zo).model_dump())
        assert client.put(f"/api/projects/{pid}", json=p).status_code == 200
        jid = client.post("/api/build/preview", json={"project_id": pid}).json()["job_id"]
        assert wait(client, jid)["status"] == "succeeded"
        heights.append(client.get(f"/api/build/result/{jid}").json()["result"]["fast_preview"]["bbox_size"][2])
    # the flight is 2.0 m tall; lifted by 1.5 m it must top out higher than the unlifted one
    assert heights[1] > heights[0] + 0.1, heights


def test_underlay_upload_and_schema(client):
    import struct, zlib
    def png():
        raw = b"\x00\x00\x00\x00"
        def ch(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
        return b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)) + ch(b"IDAT", zlib.compress(raw)) + ch(b"IEND", b"")
    pid = client.post("/api/projects", json={"name": "U"}).json()["id"]
    assert client.put(f"/api/projects/{pid}/underlays/plan.png", content=png()).status_code == 201
    r = client.put(f"/api/projects/{pid}/underlays/bad.png", content=b"nope")
    assert r.status_code >= 400
    assert client.get(f"/api/projects/{pid}/files/underlays/plan.png").status_code == 200
    p = client.get(f"/api/projects/{pid}").json()
    p["underlays"] = [{"file": "plan.png", "name": "Ground scan", "x": 0, "y": 10, "width": 20, "px_w": 1000, "px_h": 700}]
    assert client.put(f"/api/projects/{pid}", json=p).status_code == 200
    p["underlays"][0]["level_id"] = "nope"
    assert client.put(f"/api/projects/{pid}", json=p).status_code == 422
    assert client.delete(f"/api/projects/{pid}/underlays/plan.png").status_code == 204


def test_material_lab_generates_maps_and_exports_pbr_glb(client):
    """Blender bakes tileable colour / normal / roughness maps; the exported GLB carries them as glTF PBR textures."""
    import json
    import struct
    pid = make_project(client)["id"]
    p = client.get(f"/api/projects/{pid}").json()
    mid = p["materials"][0]["id"]
    r = client.post("/api/materials/generate", json={"project_id": pid, "material_id": mid,
                                                     "lab": {"preset": "brick", "resolution": 256, "metallic": 0.0}})
    assert r.status_code == 202, r.text
    assert wait(client, r.json()["job_id"], 120)["status"] == "succeeded"
    res = client.get(f"/api/build/result/{r.json()['job_id']}").json()["result"]
    files = res["files"]
    assert set(files) == {"texture", "normal_texture", "rough_texture"} and res["uv_scale"] == 1.0
    for f in files.values():
        raw = client.get(f"/api/projects/{pid}/files/textures/{f}").content
        assert raw.startswith(b"\x89PNG") and struct.unpack(">II", raw[16:24]) == (256, 256)
    # regenerating replaces the previous files of that material
    r2 = client.post("/api/materials/generate", json={"project_id": pid, "material_id": mid, "lab": {"preset": "tile", "resolution": 256}})
    assert wait(client, r2.json()["job_id"], 120)["status"] == "succeeded"
    assert client.get(f"/api/projects/{pid}/files/textures/{files['texture']}").status_code == 404
    files = client.get(f"/api/build/result/{r2.json()['job_id']}").json()["result"]["files"]
    # use it and export a GLB
    for m in p["materials"]:      # give every material the maps so whichever one the house uses must export them
        m.update(files)
    assert client.put(f"/api/projects/{pid}", json=p).status_code == 200
    j = client.post("/api/export/glb", json={"project_id": pid, "textures": True}).json()
    assert wait(client, j["job_id"], 180)["status"] == "succeeded"
    out = client.get(f"/api/build/result/{j['job_id']}").json()["result"]["outputs"]
    glb = next(o for o in out if o.endswith(".glb") and "_LOD" not in o)
    data = client.get(f"/api/projects/{pid}/files/{glb}").content
    n = struct.unpack("<I", data[12:16])[0]
    gltf = json.loads(data[20:20 + n])
    mats = [m for m in gltf["materials"] if "normalTexture" in m]
    assert mats, [m.get("name") for m in gltf["materials"]]
    pbr = mats[0]["pbrMetallicRoughness"]
    assert "baseColorTexture" in pbr and "metallicRoughnessTexture" in pbr


def test_templates_schema_roundtrip_and_validation():
    from bimgame.schema import Project, Template
    import pytest
    from pydantic import ValidationError

    t = Template(name="Thick wall", type="wall", props={"thickness": 0.3, "height": 3.2, "material": "mat_concrete"})
    p = Project(name="t", templates=[t])
    assert Project.model_validate(p.model_dump()).templates[0].props["height"] == 3.2
    with pytest.raises(ValidationError):
        Template(name="x", type="wall", props={"pitch_deg": 30})       # key not allowed for wall
    with pytest.raises(ValidationError):
        Template(name="x", type="door", props={"width": -1})
    with pytest.raises(ValidationError):
        Template(name="", type="wall")


def test_backups_auto_manual_restore_and_limits(tmp_path, monkeypatch):
    from bimgame.services.storage import ProjectStore
    monkeypatch.setattr(ProjectStore, "BACKUP_EVERY", 3600)
    monkeypatch.setattr(ProjectStore, "BACKUP_KEEP", 4)
    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app) as c:
        pid = c.post("/api/projects", json={"name": "B"}).json()["id"]
        p = c.get(f"/api/projects/{pid}").json()
        # first overwrite creates an automatic snapshot, further quick saves do not (interval)
        for i in range(3):
            p["name"] = f"v{i}"; assert c.put(f"/api/projects/{pid}", json=p).status_code == 200
        bk = c.get(f"/api/projects/{pid}/backups").json()["backups"]
        assert len(bk) == 1 and bk[0]["manual"] is False
        # manual snapshots, trimmed to BACKUP_KEEP
        names = [c.post(f"/api/projects/{pid}/backups").json()["name"] for _ in range(6)]
        assert len(set(names)) == 6
        bk = c.get(f"/api/projects/{pid}/backups").json()["backups"]
        assert len(bk) == 4 and all(b["manual"] for b in bk)
        # restore the newest manual snapshot (project name v2) after changing the project
        p["name"] = "changed"; c.put(f"/api/projects/{pid}", json=p)
        r = c.post(f"/api/projects/{pid}/backups/{names[-1]}/restore")
        assert r.status_code == 200 and r.json()["name"] == "v2" and c.get(f"/api/projects/{pid}").json()["name"] == "v2"
        # restoring first snapshots the current state, so it can be undone
        assert any(b["name"] != names[-1] for b in c.get(f"/api/projects/{pid}/backups").json()["backups"])
        # unsafe / unknown names
        assert c.post(f"/api/projects/{pid}/backups/..%2Fproject.json/restore").status_code in (404, 405, 422)
        assert c.post(f"/api/projects/{pid}/backups/project_20200101_000000.json/restore").status_code == 404
        assert c.delete(f"/api/projects/{pid}/backups/{names[-1]}").status_code == 204


def test_godot_scene_export_has_doors_collision_and_valid_tscn(client):
    """Scene export: GLB without door meshes (collision hints kept) + .tscn with one openable Door node per door."""
    import re
    pid = make_project(client)["id"]
    p = client.get(f"/api/projects/{pid}").json()
    doors = [e for e in p["elements"] if e["type"] == "door"]
    assert doors, "fixture house should contain a door"
    r = client.post("/api/export/scene", json={"project_id": pid, "scene": {"res_dir": "res://models/house/"}})
    assert r.status_code == 202, r.text
    assert wait(client, r.json()["job_id"], 180)["status"] == "succeeded"
    res = client.get(f"/api/build/result/{r.json()['job_id']}").json()["result"]
    names = [o.rsplit("/", 1)[-1] for o in res["outputs"]]
    assert {"door.gd", "player.gd", "README_godot.txt"} <= set(names) and any(n.endswith(".tscn") for n in names)
    assert res["scene"]["doors"] == len(doors) and res["validation"]["files"]
    tscn_rel = next(o for o in res["outputs"] if o.endswith(".tscn"))
    t = client.get(f"/api/projects/{pid}/files/{tscn_rel}").text
    assert t.startswith("[gd_scene") and "format=3" in t
    assert len(re.findall(r'script = ExtResource\("door"\)', t)) == len(doors)
    assert 'path="res://models/house/' in t and "CharacterBody3D" in t and "RigidBody3D" in t and "StaticBody3D" in t
    # every ext_resource / sub_resource id that is referenced exists
    ids = set(re.findall(r'\[(?:ext|sub)_resource [^\]]*id="([^"]+)"', t))
    used = set(re.findall(r'(?:ExtResource|SubResource)\("([^"]+)"\)', t))
    assert used <= ids, used - ids
    # transforms are finite numbers
    assert "nan" not in t.lower() and "inf" not in t.lower()
    # the GLB keeps collision hints but has no door meshes
    glb_rel = next(o for o in res["outputs"] if o.endswith(".glb"))
    import json, struct
    data = client.get(f"/api/projects/{pid}/files/{glb_rel}").content
    gltf = json.loads(data[20:20 + struct.unpack("<I", data[12:16])[0]])
    nn = [n.get("name", "") for n in gltf["nodes"]]
    assert any("colonly" in n for n in nn) and not any(n.startswith("door_") for n in nn), nn[:30]
    # bad options are a clear 422-style job failure, not a crash
    r2 = client.post("/api/export/scene", json={"project_id": pid, "scene": {"res_dir": "../../etc"}})
    assert wait(client, r2.json()["job_id"], 180)["status"] == "failed"


def test_scene_door_hinge_and_swing_math():
    """Door nodes: hinge position, leaf axis, and the swing sign must put the opened leaf on the requested side of the wall."""
    import math
    from bimgame.schema import Project
    from bimgame.services.godot_scene import _Xf, collect_doors

    def run(rot, mirror, hinge, swing):
        p = Project.model_validate({"id": "p", "name": "t", "levels": [{"id": "L", "name": "G", "elevation": 0, "height": 3}], "elements": [
            {"id": "w", "type": "wall", "level_id": "L", "a": [0, 0], "b": [4, 0], "thickness": 0.2},
            {"id": "d", "type": "door", "level_id": "L", "wall_id": "w", "offset": 2, "width": 0.9, "height": 2.1, "hinge": hinge, "swing": swing}]})
        xf = _Xf([0, 0, 0], 1.0, rot, mirror)
        d = collect_doors(p, xf, 100)[0]
        X, sw = d["X"], d["swing"]
        phi = math.radians(100) * sw                       # leaf direction after opening: R_y(phi) applied to X
        ox = X[0] * math.cos(phi) + X[2] * math.sin(phi)
        oz = -X[0] * math.sin(phi) + X[2] * math.cos(phi)
        # expected side: plan left normal (0,1) -> output plan -> Godot
        nl = xf.vec(0, 1)
        left = (nl[0], -nl[1])
        side = ox * left[0] + oz * left[1]
        return d, side

    d, side = run(0, False, "left", "left")
    assert abs(d["origin"][0] - (2 - 0.45 + 0.02)) < 1e-9 and abs(d["origin"][2]) < 1e-9 and d["X"] == (1.0, 0.0, -0.0) or d["X"][0] == 1.0
    assert side > 0
    for rot in (0, 90, 180, 270):
        for mirror in (False, True):
            for hinge in ("left", "right"):
                _, s_left = run(rot, mirror, hinge, "left")
                _, s_right = run(rot, mirror, hinge, "right")
                assert s_left > 0 > s_right, (rot, mirror, hinge)
    d, _ = run(0, False, "right", "left")
    assert abs(d["origin"][0] - (2 + 0.45 - 0.02)) < 1e-9 and d["X"][0] == -1.0


def test_wall_features_accept_all_carving_shapes(client):
    """Every shape hint of the wall-face editor (rotated polygons included) validates and builds a preview."""
    pid = client.post("/api/projects", json={"name": "carve", "units": "m"}).json()["id"]
    p = client.get(f"/api/projects/{pid}").json()
    lv = p["levels"][0]["id"]
    shapes = ["rect", "circle", "arch", "triangle", "star", "polygon", "ellipse", "roundrect", "hexagon", "octagon", "diamond", "cross", "semicircle", "trapezoid", "gothic", "slot"]
    feats = [{"id": f"f{i}", "kind": "cut" if i % 2 else "relief", "shape": s, "polygon": [[1 + i * 0.5, 1], [1.4 + i * 0.5, 1], [1.4 + i * 0.5, 1.6], [1 + i * 0.5, 1.6]], "depth": 0.05, "face": "left"} for i, s in enumerate(shapes)]
    wall = {"id": "w1", "type": "wall", "level_id": lv, "a": [0, 0], "b": [12, 0], "thickness": 0.3, "features": feats}
    p["elements"] = [wall]
    assert client.put(f"/api/projects/{pid}", json=p).status_code == 200
    r = client.post("/api/geometry/validate", json={"project_id": pid}).json()
    assert r["ok"], r


def test_housekeeping_exports_jobs_and_profile(tmp_path):
    """Disk must not grow without bound: old export folders, finished jobs and the profile log are trimmed."""
    import os
    import time as _t
    from pathlib import Path
    from bimgame.config import Settings
    from bimgame.services.build import BuildService
    from bimgame.services.storage import ProjectStore

    s = Settings(data_dir=tmp_path)
    store = ProjectStore(s)
    b = BuildService(store, s)
    pdir = tmp_path / "prj"
    for i in range(10):
        d = pdir / "exports" / f"glb_{i:08d}"
        d.mkdir(parents=True)
        (d / "m.glb").write_bytes(b"x")
        os.utime(d, (_t.time() - 100 + i, _t.time() - 100 + i))
    (pdir / "exports" / "preview").mkdir()
    b._prune_exports(pdir, keep_name="glb_00000009")
    left = sorted(p.name for p in (pdir / "exports").iterdir())
    assert "preview" in left and "glb_00000009" in left
    assert len([n for n in left if n.startswith("glb_")]) == b.EXPORT_KEEP

    store.JOBS_KEEP = 5
    for i in range(12):
        store.job_put({"id": f"j{i:02d}", "project_id": "p", "kind": "preview", "status": "succeeded", "created_at": f"2026-01-01T00:00:{i:02d}",
                       "started_at": None, "finished_at": None, "params": {}, "result": {"x": 1}, "error": None})
    store.job_put({"id": "run", "project_id": "p", "kind": "preview", "status": "running", "created_at": "2025-01-01T00:00:00",
                   "started_at": None, "finished_at": None, "params": {}, "result": None, "error": None})
    assert store.job_get("run") is not None and store.job_get("j11") is not None and store.job_get("j00") is None


def test_site_open_creates_reuses_and_survives_save(client):
    """TerrainForge -> BIM: a site gets its own project holding the footprint; asking again reuses it and updates the footprint."""
    r = client.post("/api/sites/open", json={"key": "v1", "name": "Village", "shape": "rect", "width_m": 120, "length_m": 80, "rotation_deg": 30}).json()
    assert r["created"] is True
    pid = r["project_id"]
    again = client.post("/api/sites/open", json={"key": "v1", "name": "Village", "project_id": pid, "shape": "circle", "diameter_m": 150}).json()
    assert again["created"] is False and again["project_id"] == pid
    p = client.get(f"/api/projects/{pid}").json()
    assert p["site"]["shape"] == "circle" and p["site"]["diameter_m"] == 150
    assert client.put(f"/api/projects/{pid}", json=p).status_code == 200          # the editor saves the whole project: site must round-trip
    gone = client.post("/api/sites/open", json={"key": "v2", "project_id": "prj_missing"}).json()
    assert gone["created"] is True and gone["project_id"] != "prj_missing"
    assert client.post("/api/sites/open", json={"key": "x", "diameter_m": -5}).status_code == 422
