"""واجهات التصدير الجديدة: GLB و.blend (Blender مزيّف بسكربت) وخامات CC0، وبقاء التصدير القديم (zip) سليماً."""
import io, json, os, stat, time, zipfile
import cv2, httpx, numpy as np, pytest
from fastapi.testclient import TestClient
from app import texlib, blendexport
from app.main import app
from tests.test_terrain import proj, pf
from tests.test_glb import parse
from tests.test_textures import ph_routes, net  # noqa: F401  (fixture)

C = TestClient(app)


def wait(jid, t=60):
    end = time.time() + t
    while time.time() < end:
        s = C.get(f"/api/job/{jid}").json()
        if s["state"] != "running":
            return s
        time.sleep(0.1)
    raise AssertionError("timeout")


def small(**kw):
    p = proj([pf(x_m=500, y_m=500, diameter_m=500)], noise=0.0, export=dict(resolution=513, mask_px=513, glb_resolution=257, glb_texture_px=1024), **kw)
    return json.loads(p.model_dump_json())


def test_capabilities_and_glb_job_roundtrip():
    cap = C.get("/api/export-capabilities").json()
    assert cap["glb"]["available"] is True and "available" in cap["blend"]
    r = C.post("/api/export-world?fmt=glb", json=small()); assert r.status_code == 200
    s = wait(r.json()["job_id"]); assert s["state"] == "done", s
    d = C.get(f"/api/job/{r.json()['job_id']}/download")
    assert d.headers["content-type"] == "model/gltf-binary" and d.headers["content-disposition"].endswith('filename="world.glb"')
    js, _ = parse(d.content)
    assert js["asset"]["generator"] == "TerrainForge"


def test_preview_glb_is_light_and_valid():
    r = C.post("/api/preview-glb?res=129&tex=256", json=small()); assert r.status_code == 200
    js, _ = parse(r.content); assert len(js["meshes"]) >= 2 and json.loads(r.headers["x-tf-report"])["vertices"] == 129 * 129


def test_bad_format_and_errors_block_export():
    assert C.post("/api/export-world?fmt=obj", json=small()).status_code == 422
    bad = small(); bad["world"]["size_x_m"] = -5
    assert C.post("/api/export-world?fmt=glb", json=bad).status_code == 422


@pytest.fixture
def fake_blender(tmp_path, monkeypatch):
    sh = tmp_path / "fake_blender.sh"
    def make(body):
        sh.write_text("#!/bin/sh\nif [ \"$1\" = \"-c\" ]; then echo TF_OK; exit 0; fi\n" + body); sh.chmod(sh.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("TERRAIN_BLENDER_PYTHON", str(sh)); monkeypatch.delenv("TERRAIN_BLENDER_CMD", raising=False)
    blendexport._CHECK.update(t=0.0, v=None)
    make('test -f "$2" && test -f "$(dirname "$2")/import_build.py" || exit 3\ncp "$2" "$3"\n')
    yield make
    blendexport._CHECK.update(t=0.0, v=None)


def test_blend_export_runs_blender_with_full_build_dir(fake_blender):
    r = C.post("/api/export-world?fmt=blend", json=small()); assert r.status_code == 200, r.text
    s = wait(r.json()["job_id"]); assert s["state"] == "done", s
    d = C.get(f"/api/job/{r.json()['job_id']}/download")
    assert ".blend" in d.headers["content-disposition"]
    assert json.loads(d.content)["format"] == "terrainforge-build"          # السكربت المزيّف نسخ build.json: أي أن Blender استلم المجلد الكامل


def test_blend_failure_timeout_and_unavailable(fake_blender, monkeypatch):
    fake_blender('echo boom >&2; exit 1\n')
    r = C.post("/api/export-world?fmt=blend", json=small()); s = wait(r.json()["job_id"])
    assert s["state"] == "error" and "boom" in s["error"] and "رمز 1" in s["error"]
    fake_blender('sleep 20\n'); monkeypatch.setenv("TERRAIN_BLENDER_TIMEOUT", "1")
    r = C.post("/api/export-world?fmt=blend", json=small()); s = wait(r.json()["job_id"], 30)
    assert s["state"] == "error" and "مهلة" in s["error"]
    monkeypatch.delenv("TERRAIN_BLENDER_PYTHON"); blendexport._CHECK.update(t=0.0, v=None)
    r = C.post("/api/export-world?fmt=blend", json=small())
    assert r.status_code == 503 and "GLB" in r.json()["detail"]


def test_texture_endpoints_and_export_zip_carries_pack_and_credits(net, tmp_path):  # noqa: F811
    ph_routes(net)
    r = C.post("/api/textures/fetch", json={"provider": "polyhaven", "asset_id": "rock_01"}); assert r.status_code == 200, r.text
    folder = r.json()["folder"]
    assert C.get("/api/textures/cache").json()["items"][0]["id"] == "rock_01"
    assert C.get("/api/textures/file/polyhaven/rock_01/rock_01_diff_1k.jpg").status_code == 200
    assert C.get("/api/textures/file/polyhaven/rock_01/..%2Fsource.json").status_code in (404, 422)
    assert C.post("/api/textures/fetch", json={"provider": "polyhaven", "asset_id": "../x"}).status_code == 422
    assert r.json()["ref"] == "cc0:polyhaven/rock_01"
    p = small(materials=[dict(id="grass", color="#5c8a3c", pack=r.json()["ref"], tile_m=8)])             # مرجع قابل للنقل لا مسار مطلق
    z = zipfile.ZipFile(io.BytesIO(C.post("/api/export", json=p).content)); names = z.namelist()
    assert "heightmap_16bit.png" in names and "build.json" in names and "import_build.py" in names     # التصدير القديم محفوظ كما هو
    assert "textures/polyhaven_rock_01/rock_01_diff_1k.jpg" in names and "textures/CREDITS.txt" in names
    bj = json.loads(z.read("build.json")); g = next(m for m in bj["materials"] if m["id"] == "grass")
    assert g["pack"] == "textures/polyhaven_rock_01" and "CC0" in z.read("textures/CREDITS.txt").decode()
    glbd = C.post("/api/preview-glb?res=65&tex=256", json=p); js, _ = parse(glbd.content)
    assert "polyhaven/rock_01" in js["asset"]["extras"]["credits"] or "Poly Haven" in js["asset"]["extras"]["credits"]


def test_ref_resolution_missing_ref_falls_back_and_ensure_downloads(net, tmp_path):  # noqa: F811
    p = small(materials=[dict(id="grass", color="#5c8a3c", pack="cc0:polyhaven/rock_01", tile_m=8)])
    z = zipfile.ZipFile(io.BytesIO(C.post("/api/export", json=p).content))            # غير منزّلة: لا انهيار، تبقى المادة بلونها
    assert not any(n.startswith("textures/") for n in z.namelist())
    ph_routes(net)
    r = C.post("/api/textures/ensure", json={"refs": ["cc0:polyhaven/rock_01", "cc0:polyhaven/rock_01", "not-a-ref", "cc0:evil/x"]}).json()["results"]
    assert r[0] == {"ref": "cc0:polyhaven/rock_01", "ok": True, "cached": False} and len(r) == 2
    assert r[1]["ref"] == "cc0:evil/x" and r[1]["ok"] is False and "مصدر" in r[1]["error"]        # مصدر مجهول يُبلَّغ ولا يُنفَّذ
    z = zipfile.ZipFile(io.BytesIO(C.post("/api/export", json=p).content))
    assert "textures/polyhaven_rock_01/rock_01_diff_1k.jpg" in z.namelist()
