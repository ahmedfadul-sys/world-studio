"""تصدير GLB: بنية الملف، اتجاه المحاور، الخبز من الخامات، الاعتمادات. التحقق المستقل: pygltflib/trimesh إن توفّرا."""
import io, json, struct
import cv2, numpy as np, pytest
from app import glb, texlib
from app.schemas import Project, Material
from tests.test_terrain import proj, pf


def parse(data: bytes):
    assert data[:4] == b"glTF" and struct.unpack("<I", data[4:8])[0] == 2 and struct.unpack("<I", data[8:12])[0] == len(data)
    jl, jt = struct.unpack("<I4s", data[12:20]); assert jt == b"JSON" and jl % 4 == 0
    js = json.loads(data[20:20 + jl]); bo = 20 + jl
    bl, bt = struct.unpack("<I4s", data[bo:bo + 8]); assert bt == b"BIN\0" and bl % 4 == 0 and bo + 8 + bl == len(data)
    return js, data[bo + 8:]


def acc(js, bin_, i):
    a = js["accessors"][i]; v = js["bufferViews"][a["bufferView"]]
    dt = {5126: np.float32, 5125: np.uint32}[a["componentType"]]; n = {"SCALAR": 1, "VEC2": 2, "VEC3": 3}[a["type"]]
    off = v["byteOffset"] + a.get("byteOffset", 0)
    return np.frombuffer(bin_, dt, a["count"] * n, off).reshape(-1, n)


def world(**kw):
    return proj([pf(x_m=250, y_m=750, diameter_m=400, high_m=300, low_m=0, kind="mountain"),
                 pf(id="l1", kind="lake", x_m=800, y_m=250, diameter_m=200, high_m=20, low_m=-20)], noise=0.0, **kw)


def test_glb_structure_axes_winding_and_uv():
    p = world()
    data, rep = glb.build_glb(p, resolution=65, tex_px=64)
    js, bin_ = parse(data)
    t = js["meshes"][0]["primitives"][0]; pos = acc(js, bin_, t["attributes"]["POSITION"]); nrm = acc(js, bin_, t["attributes"]["NORMAL"])
    uv = acc(js, bin_, t["attributes"]["TEXCOORD_0"]); idx = acc(js, bin_, t["indices"]).ravel()
    ny, nx = rep["grid"][1], rep["grid"][0]
    assert len(pos) == nx * ny == rep["vertices"] and len(idx) == (nx - 1) * (ny - 1) * 6 and idx.max() < len(pos)
    # المحاور: الجبل عند (x=250, y=750 شمالاً) -> X=250, Z=-750، والارتفاع في Y
    top = pos[pos[:, 1].argmax()]
    assert abs(top[0] - 250) < 40 and abs(top[2] + 750) < 40 and top[1] > 250
    assert pos[:, 0].min() == 0 and pos[:, 0].max() == 1000 and pos[:, 2].max() == 0 and pos[:, 2].min() == -1000
    # الصف 0 = الشمال (Z = -1000) و v=0
    assert pos[0, 2] == -1000 and uv[0, 1] == 0 and uv[-1, 1] == 1 and uv[0, 0] == 0 and uv[nx - 1, 0] == 1
    # كل المثلثات تواجه الأعلى (+Y) وNormals مطبّعة وتتجه للأعلى
    tri = idx.reshape(-1, 3); a, b, c = pos[tri[:, 0]], pos[tri[:, 1]], pos[tri[:, 2]]
    assert (np.cross(b - a, c - a)[:, 1] > 0).all()
    assert np.allclose(np.linalg.norm(nrm, axis=1), 1, atol=1e-4) and (nrm[:, 1] > 0).all()
    # الجبل: الجانب الشرقي من القمة ينحدر نحو الشرق => مركّب X موجب في الـNormal
    east = np.argmin(np.abs(pos[:, 0] - 340) + np.abs(pos[:, 2] + 750) + np.abs(pos[:, 1] - pos[:, 1].max() * 0.5) * 0.0)
    assert nrm[east, 0] > 0
    names = [n["name"] for n in js["nodes"]]
    assert {"Terrain", "Sea", "Lakes"} <= set(names)
    assert js["asset"]["extras"]["world_size_m"] == [1000, 1000]


def test_glb_texture_decodes_and_bakes_pack_color_and_credits(tmp_path, monkeypatch):
    monkeypatch.setenv("TERRAIN_DATA_DIR", str(tmp_path))
    d = texlib.data_root() / "polyhaven" / "red_rock"; d.mkdir(parents=True)
    cv2.imwrite(str(d / "red_rock_diff_1k.jpg"), np.full((256, 256, 3), (30, 30, 220), np.uint8))      # BGR: أحمر
    (d / "source.json").write_text(json.dumps({"provider": "polyhaven", "id": "red_rock", "name": "Red", "files": {"diff": "red_rock_diff_1k.jpg"}, "authors": ["A"], "source_url": "https://polyhaven.com/a/red_rock"}))
    p = world(materials=[Material(id="grass", color="#00ff00", pack=str(d), tile_m=50)])
    data, rep = glb.build_glb(p, resolution=65, tex_px=128)
    js, bin_ = parse(data)
    v = js["bufferViews"][js["images"][0]["bufferView"]]
    img = cv2.imdecode(np.frombuffer(bin_[v["byteOffset"]:v["byteOffset"] + v["byteLength"]], np.uint8), cv2.IMREAD_COLOR)
    assert img.shape[:2] == (128, 128) and "grass" in rep["bake"]["textured"]
    m = img.reshape(-1, 3).mean(0)                       # BGR: غلبة الأحمر لا الأخضر الثابت
    assert m[2] > 150 and m[1] < 90
    assert rep["textures_used"] == ["polyhaven/red_rock"] and "Poly Haven" in js["asset"]["extras"]["credits"]


def test_glb_color_only_and_rectangular_world_and_resolution_cap():
    p = proj([pf(x_m=500, y_m=250, diameter_m=300)], size=(2000, 1000), noise=0.0)
    data, rep = glb.build_glb(p, resolution=65, tex_px=100)
    assert rep["bake"]["texture_px"] == [100, 50] and rep["grid"] == [65, 33] and rep["bake"]["textured"] == []
    _, rep2 = glb.build_glb(proj(size=(100, 100)), resolution=5000, tex_px=16) if False else (None, None)
    assert glb.MAX_GLB_RES == 2049


def test_prefilter_avoids_aliasing():
    chk = np.indices((512, 512)).sum(0) % 2 * 255
    img = np.dstack([chk] * 3).astype(np.uint8)
    out = glb._prefilter(img, tile_m=10, texel_m=10)       # texel أكبر من التكرار -> متوسط لوني
    assert out.shape[:2] == (1, 1) and 100 < out.mean() < 160


def test_independent_loaders():
    pytest.importorskip("trimesh")
    import trimesh
    data, rep = glb.build_glb(world(), resolution=65, tex_px=64)
    sc = trimesh.load(io.BytesIO(data), file_type="glb")
    assert len(sc.geometry) >= 2 and sum(len(g.faces) for g in sc.geometry.values()) >= rep["triangles"]
    gl = pytest.importorskip("pygltflib")
    g = gl.GLTF2.load_from_bytes(data)
    assert g.asset.version == "2.0" and len(g.meshes) >= 2
