"""مكتبة الخامات: كل الشبكة مزيّفة (httpx.MockTransport) — لا اتصال حقيقي. تتحقق من ترخيص CC0 والدقة 1K وسلامة الملفات والأمان."""
import hashlib, io, json, zipfile
import cv2, httpx, numpy as np, pytest
from app import texlib
from app.texlib import TexError


def jpg(side=64, v=120, ext=".jpg"):
    return cv2.imencode(ext, np.full((side, side, 3), v, np.uint8))[1].tobytes()


@pytest.fixture
def net(tmp_path, monkeypatch):
    monkeypatch.setenv("TERRAIN_DATA_DIR", str(tmp_path))
    texlib.PolyHaven._list_cache = None
    state = {"hits": [], "routes": {}}

    def handler(req: httpx.Request):
        state["hits"].append(str(req.url))
        r = state["routes"].get(str(req.url))
        if r is None:
            return httpx.Response(404)
        return r(req) if callable(r) else r
    monkeypatch.setattr(texlib, "make_client", lambda: httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False))
    return state


def ph_routes(net, aid="rock_01", **over):
    d = jpg(); n = jpg(v=200, ext=".png")
    net["routes"].update({
        f"https://api.polyhaven.com/info/{aid}": httpx.Response(200, json={"name": "Rock 01", "authors": {"Rob Tuytel": "All"}, **over.get("info", {})}),
        f"https://api.polyhaven.com/files/{aid}": httpx.Response(200, json={
            "Diffuse": {"1k": {"jpg": {"url": f"https://dl.polyhaven.org/{aid}_diff_1k.jpg", "md5": hashlib.md5(d).hexdigest(), "size": len(d)}}, "2k": {"jpg": {"url": "https://dl.polyhaven.org/BIG.jpg"}}},
            "Rough": {"1k": {"jpg": {"url": f"https://dl.polyhaven.org/{aid}_rough_1k.jpg"}}},
            "nor_gl": {"1k": {"png": {"url": f"https://dl.polyhaven.org/{aid}_nor.png"}}},
            "Displacement": {"1k": {"jpg": {"url": f"https://dl.polyhaven.org/{aid}_disp_1k.jpg"}}}}),
        f"https://dl.polyhaven.org/{aid}_diff_1k.jpg": httpx.Response(200, content=d),
        f"https://dl.polyhaven.org/{aid}_rough_1k.jpg": httpx.Response(200, content=jpg(v=90)),
        f"https://dl.polyhaven.org/{aid}_nor.png": httpx.Response(200, content=n),
        f"https://dl.polyhaven.org/{aid}_disp_1k.jpg": httpx.Response(200, content=jpg(v=60)),
    })


def test_polyhaven_fetch_1k_only_names_match_importer_and_cached(net):
    ph_routes(net)
    r = texlib.fetch("polyhaven", "rock_01")
    assert r["license"] == "CC0-1.0" and r["resolution"] == "1k" and r["cached"] is False
    assert r["files"] == {"diff": "rock_01_diff_1k.jpg", "rough": "rock_01_rough_1k.jpg", "nor_gl": "rock_01_nor_gl_1k.png", "disp": "rock_01_disp_1k.jpg"}
    assert not any("BIG.jpg" in h for h in net["hits"])                    # لم تُنزَّل 2K أبداً
    n = len(net["hits"])
    assert texlib.fetch("polyhaven", "rock_01")["cached"] is True and len(net["hits"]) == n   # الكاش: بلا شبكة
    assert texlib.is_managed(r["folder"]) and not texlib.is_managed("/tmp")
    assert texlib.cached()[0]["id"] == "rock_01"


def test_non_cc0_rejected_and_nothing_left_behind(net, tmp_path):
    ph_routes(net, info={"license": "CC-BY-4.0"})
    with pytest.raises(TexError, match="CC0"):
        texlib.fetch("polyhaven", "rock_01")
    assert not list((tmp_path / "textures").glob("**/*.jpg"))


def test_md5_mismatch_rejected(net):
    ph_routes(net)
    net["routes"]["https://dl.polyhaven.org/rock_01_diff_1k.jpg"] = httpx.Response(200, content=jpg(v=1))
    with pytest.raises(TexError, match="md5"):
        texlib.fetch("polyhaven", "rock_01")
    assert texlib.cached() == []


def test_oversize_image_rejected(net):
    ph_routes(net)
    net["routes"]["https://dl.polyhaven.org/rock_01_rough_1k.jpg"] = httpx.Response(200, content=jpg(side=2300))
    with pytest.raises(TexError, match="1K"):
        texlib.fetch("polyhaven", "rock_01")


@pytest.mark.parametrize("bad", ["../etc", "a/b", "", "x" * 200, "a b", "a;b"])
def test_bad_ids_rejected(net, bad):
    with pytest.raises(TexError):
        texlib.fetch("polyhaven", bad)


def test_unknown_provider_and_foreign_host_and_http(net):
    with pytest.raises(TexError, match="مصدر"):
        texlib.fetch("evil", "x")
    ph_routes(net)
    net["routes"]["https://dl.polyhaven.org/rock_01_diff_1k.jpg"] = httpx.Response(302, headers={"location": "https://evil.example.com/a.jpg"})
    with pytest.raises(TexError, match="مضيف"):
        texlib.fetch("polyhaven", "rock_01")
    net["routes"]["https://dl.polyhaven.org/rock_01_diff_1k.jpg"] = httpx.Response(302, headers={"location": "http://dl.polyhaven.org/a.jpg"})
    with pytest.raises(TexError, match="مضيف"):                             # http غير مسموح
        texlib.fetch("polyhaven", "rock_01")


def test_polyhaven_search_filters_locally(net):
    net["routes"]["https://api.polyhaven.com/assets?type=textures"] = httpx.Response(200, json={
        "rock_01": {"name": "Rock 01", "categories": ["rock"], "tags": ["cliff"]}, "grass_02": {"name": "Grass", "categories": ["ground"], "tags": []},
        "../bad": {"name": "x"}})
    assert [h["id"] for h in texlib.search("polyhaven", "rock")] == ["rock_01"]
    assert sorted(h["id"] for h in texlib.search("polyhaven", "")) == ["grass_02", "rock_01"]


def acg_zip(extra=None):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("Rock030_1K-JPG_Color.jpg", jpg()); z.writestr("Rock030_1K-JPG_NormalGL.jpg", jpg(v=9)); z.writestr("Rock030_1K-JPG_NormalDX.jpg", jpg(v=8))
        z.writestr("Rock030_1K-JPG_Roughness.jpg", jpg(v=7)); z.writestr("Rock030_1K-JPG_Displacement.jpg", jpg(v=6)); z.writestr("Rock030.usdc", b"x")
        for k, v in (extra or {}).items():
            z.writestr(k, v)
    return b.getvalue()


def acg_listing(attr="1K-JPG", **extra):
    return httpx.Response(200, json={"foundAssets": [{"assetId": "Rock030", "displayName": "Rock 030", **extra, "downloadFolders": {"default": {"downloadFiletypeCategories": {"zip": {"downloads": [
        {"attribute": "2K-JPG", "downloadLink": "https://ambientcg.com/get?file=Rock030_2K-JPG.zip"},
        {"attribute": attr, "downloadLink": "https://ambientcg.com/get?file=Rock030_1K-JPG.zip"}]}}}}}]})


def test_ambientcg_fetch_extracts_only_wanted_maps_safely(net):
    net["routes"]["https://ambientcg.com/api/v2/full_json?type=Material&id=Rock030&include=downloadData,displayData"] = acg_listing()
    net["routes"]["https://ambientcg.com/get?file=Rock030_1K-JPG.zip"] = httpx.Response(302, headers={"location": "https://f003.backblazeb2.com/file/x/Rock030_1K-JPG.zip"})
    net["routes"]["https://f003.backblazeb2.com/file/x/Rock030_1K-JPG.zip"] = httpx.Response(200, content=acg_zip({"../../evil_Color.jpg": jpg()}))
    r = texlib.fetch("ambientcg", "Rock030")
    assert r["files"] == {"diff": "Rock030_diff_1k.jpg", "nor_gl": "Rock030_nor_gl_1k.jpg", "rough": "Rock030_rough_1k.jpg", "disp": "Rock030_disp_1k.jpg"} or set(r["files"]) == {"diff", "nor_gl", "rough", "disp"}
    names = sorted(p.name for p in (texlib.data_root() / "ambientcg" / "Rock030").iterdir())
    assert all(n.startswith("Rock030_") or n == "source.json" for n in names) and not any("evil" in n or "usdc" in n for n in names)
    assert not any("2K" in h for h in net["hits"])


def test_ambientcg_no_1k_or_non_cc0(net):
    net["routes"]["https://ambientcg.com/api/v2/full_json?type=Material&id=Rock030&include=downloadData,displayData"] = acg_listing(attr="4K-JPG")
    with pytest.raises(TexError, match="1K"):
        texlib.fetch("ambientcg", "Rock030")
    net["routes"]["https://ambientcg.com/api/v2/full_json?type=Material&id=Rock030&include=downloadData,displayData"] = acg_listing(license="CC-BY")
    with pytest.raises(TexError, match="CC0"):
        texlib.fetch("ambientcg", "Rock030")


def test_credits_text(net):
    ph_routes(net)
    t = texlib.credits_text([texlib.fetch("polyhaven", "rock_01")])
    assert "CC0" in t and "Poly Haven" in t and "rock_01" in t
