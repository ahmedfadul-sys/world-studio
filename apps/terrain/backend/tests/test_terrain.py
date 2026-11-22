import io, json, math, os, tempfile, zipfile
import numpy as np
import pytest
import cv2
from app.schemas import Project
from app.terrain import Engine, engine_for, grid_axes, validate, S
from app.exporter import normalize, build_zip
from app.tiles import export_tiles, tile_axes, tile_plan
from app.materials import paint as paint_fn, pack_splats, colors_rgb, hex_rgb
from app.routing import route, suggest_sites, lots_for_site
from app.gameplay import simulate, viewshed, rays
from app.schemas import Poi


def proj(points=(), lines=(), cells=(), biomes=(), size=(1000, 1000), noise=30.0, export=None, erosion=None, sites=(), zones=(), paint=None, materials=(), **base):
    return Project(world=dict(size_x_m=size[0], size_y_m=size[1], cell_size_m=100, chunk_size_m=500, seed=3),
                   base=dict(noise_amplitude_m=noise, **base), points=list(points), lines=list(lines),
                   cells=list(cells), biomes=list(biomes), export=export or {}, erosion=erosion or {}, sites=list(sites), zones=list(zones), paint=paint or {}, materials=list(materials))


def pf(**kw):
    d = dict(id="m1", kind="mountain", x_m=500, y_m=500, diameter_m=600, high_m=500, low_m=50, shape="cone", roughness=0.5, seed=5)
    d.update(kw)
    return d


def run(p, res=101):
    xs, ys = grid_axes(p.world.size_x_m, p.world.size_y_m, res)
    return xs, ys, Engine(p, step=5).grid(xs, ys)


POS = ["mountain", "hill", "plateau", "mesa", "volcano", "island", "atoll", "terraces", "scree", "delta"]
NEG = ["crater", "basin", "lake", "sinkhole", "cave", "marsh"]
ALL = POS + NEG + ["dune"]


def kw_for(k):
    if k in POS:
        return dict(high_m=500, low_m=50)
    if k == "crater":
        return dict(high_m=60, low_m=-80)
    if k == "dune":
        return dict(amplitude_m=15, wavelength_m=60, direction_deg=30)
    return dict(high_m=50, low_m=-80)


def test_all_kinds_deterministic_finite_and_inside_footprint():
    """كل أنواع التضاريس: حتمية، منتهية، وبصمتها لا تتجاوز القطر المُدخل."""
    for k in ALL:
        p0 = proj(noise=0.0)
        p1 = proj([pf(kind=k, diameter_m=400, roughness=0.3, **kw_for(k))], noise=0.0)
        xs, ys, a = run(p0, 201)
        _, _, b = run(p1, 201)
        _, _, b2 = run(p1, 201)
        assert np.array_equal(b, b2) and np.isfinite(b).all(), k
        ch = np.argwhere(np.abs(a - b) > 1e-3)
        assert len(ch) > 0, k
        d = np.hypot(xs[ch[:, 1]] - 500, ys[ch[:, 0]] - 500)
        assert d.max() <= 200 + 1.0, (k, d.max())


def test_footprint_fills_circle_when_roughness_zero():
    for k in ["mountain", "hill", "plateau", "mesa", "volcano", "island", "terraces", "basin", "lake", "sinkhole"]:
        p0 = proj(noise=0.0)
        p1 = proj([pf(kind=k, diameter_m=400, roughness=0.0, **kw_for(k))], noise=0.0)
        xs, ys, a = run(p0, 201)
        _, _, b = run(p1, 201)
        ch = np.argwhere(np.abs(a - b) > 1e-3)
        d = np.hypot(xs[ch[:, 1]] - 500, ys[ch[:, 0]] - 500)
        assert d.max() >= 0.88 * 200, (k, d.max())


def test_peak_exact_for_main_positive_kinds():
    for k in ("mountain", "hill", "plateau", "mesa", "island"):
        _, _, Z = run(proj([pf(kind=k)]))
        assert abs(Z[50, 50] - 500) < 0.01, k


def test_window_independence_no_seams():
    p = proj([pf(), pf(id="d", kind="dune", x_m=150, y_m=150, diameter_m=200, amplitude_m=10)])
    xs, ys, full = run(p)
    left = Engine(p, step=5).grid(xs[:51], ys)
    assert np.array_equal(full[:, :51], left)


def test_rectangular_world_uniform_scale():
    xs, ys = grid_axes(8000, 2000, 1025)
    assert len(xs) == 1025 and len(ys) == 257 and abs((xs[1] - xs[0]) - (ys[0] - ys[1])) < 0.01


def test_nesting_rules():
    big = pf(id="big", kind="plateau", diameter_m=800, high_m=300, low_m=50, inner_ratio=0.5)
    lake_in = pf(id="l", kind="lake", x_m=500, y_m=500, diameter_m=200, high_m=300, low_m=250)
    p = proj([big, lake_in]); e, _ = validate(p, engine_for(p, 513))
    assert not any("تداخل" in m for m in e)                                    # بحيرة فوق هضبة: منطقي
    mtn_in = pf(id="mm", kind="mountain", x_m=500, y_m=500, diameter_m=200)
    lake_big = pf(id="lb", kind="lake", diameter_m=800, high_m=50, low_m=-50)
    p = proj([lake_big, pf(id="v", kind="volcano", diameter_m=200, high_m=300, low_m=50)])
    e, _ = validate(p, engine_for(p, 513)); assert not any("غير منطقي" in m for m in e)   # بركان جزيرة داخل بحيرة
    p = proj([pf(id="a", kind="mountain", diameter_m=800), mtn_in]); e, _ = validate(p, engine_for(p, 513))
    assert any("غير منطقي" in m for m in e)                                    # جبل داخل جبل: لا
    p = proj([pf(id="a", x_m=300, diameter_m=400), pf(id="b", x_m=600, diameter_m=400)]); e, _ = validate(p, engine_for(p, 513))
    assert any("جزئي" in m for m in e)                                         # تداخل جزئي: خطأ
    p = proj([pf(id="a", x_m=300, diameter_m=400), pf(id="b", x_m=700, diameter_m=400)]); e, _ = validate(p, engine_for(p, 513))
    assert not any("تداخل" in m for m in e)                                    # تلامس: مسموح


def test_nested_lake_carves_inside_host_surface():
    host = pf(id="h", kind="plateau", diameter_m=800, high_m=300, low_m=50, inner_ratio=0.6, roughness=0)
    lake = pf(id="l", kind="lake", diameter_m=200, high_m=300, low_m=270, inner_ratio=0.3, roughness=0)
    _, _, Z = run(proj([host, lake], noise=0.0), 201)
    assert abs(Z[100, 100] - 270) < 0.01 and abs(Z[100, 130] - 300) < 0.5


def test_cell_is_planar_with_user_slope_and_blends_at_edges():
    cells = [dict(col=5, row=5, elevation_m=100, rise_m=1, run_m=50, aspect_deg=90)]     # 2% شرقاً
    p = proj(cells=cells, noise=0.0, elevation_m=0)
    e = Engine(p)
    cx, cy = 550.0, 450.0
    z0 = e.points([cx], [cy])[0]
    assert abs(z0 - 100) < 1e-3
    xs = np.array([cx - 20, cx - 10, cx, cx + 10, cx + 20])                      # داخل الخلية (±25 م مستوية تماماً)
    z = e.points(xs, np.full(5, cy))
    assert np.allclose(np.diff(z) / 10.0, 0.02, atol=1e-4)
    zn = e.points([cx], [cy + 20])[0]                                             # لا ميل شمالاً
    assert abs(zn - 100) < 1e-3
    edge = e.points([cx + 50 + 40], [cy])[0]                                      # بعد الحدود بـ 40 م: عاد للأرض (0)
    assert abs(edge) < 0.01
    xe = np.linspace(cx + 25, cx + 75, 60)
    ze = e.points(xe, np.full(60, cy))
    assert np.all(np.abs(np.diff(ze)) < 5.0)                                      # انتقال ناعم بلا قفزة


def test_adjacent_cells_blend_without_dip():
    cells = [dict(col=5, row=5, elevation_m=100), dict(col=6, row=5, elevation_m=100)]
    p = proj(cells=cells, noise=0.0, elevation_m=0)
    z = Engine(p).points(np.linspace(560, 640, 41), np.full(41, 450.0))
    assert z.min() > 99.99                                                        # لا انخفاض عند الحد المشترك


def test_points_mode_matches_grid():
    p = proj([pf(kind="volcano", inner_ratio=0.15), pf(id="d", kind="delta", x_m=150, y_m=850, diameter_m=250, high_m=60, low_m=20, steps=3, amplitude_m=8, wavelength_m=15)],
             cells=[dict(col=2, row=2, elevation_m=120, rise_m=2, run_m=50, aspect_deg=45)])
    xs, ys, Z = run(p)
    e = Engine(p, step=5)
    X, Y = np.meshgrid(xs[::7], ys[::7])
    assert np.allclose(e.points(X.ravel(), Y.ravel()), Z[::7, ::7].ravel(), atol=1e-3)


def river(points, **kw):
    d = dict(id="r1", kind="river", points=points, width_m=30, depth_m=5)
    d.update(kw)
    return d


def test_river_bed_monotone_and_waterfall_step():
    cells = [dict(col=c, row=r, elevation_m=200 - 15 * c) for c in range(10) for r in range(10)]
    p = proj(lines=[river([(50, 500), (500, 560), (950, 500)], falls=[dict(at=0.5, height_m=20, length_m=10)])], cells=cells, noise=20.0)
    e = Engine(p, step=5)
    d = e._design(0)
    assert np.all(np.diff(d["bed"]) <= 1e-6)
    assert len(e.waterfalls()) == 1
    s = d["s"]; i = np.argmin(np.abs(s - 0.5 * d["L"]))
    drop = d["bed"][max(i - 6, 0)] - d["bed"][min(i + 6, len(s) - 1)]
    assert drop > 20                                                              # الهبوط ≥ ارتفاع الشلال


def test_river_climbing_warns_and_core_is_error():
    cells = [dict(col=c, row=r, elevation_m=20 + 15 * c) for c in range(10) for r in range(10)]
    p = proj(lines=[river([(50, 500), (950, 500)])], cells=cells, noise=0.0)
    _, w = validate(p, engine_for(p, 513))
    assert any("يصعد" in m or "أعلى من المنبع" in m for m in w)
    p = proj([pf(diameter_m=600)], lines=[river([(50, 500), (950, 500)])])
    e, _ = validate(p, engine_for(p, 513)); assert any("قلب" in m for m in e)
    p = proj([pf(diameter_m=600)], lines=[river([(50, 900), (950, 900)])])
    e, _ = validate(p, engine_for(p, 513)); assert not any("قلب" in m for m in e)


def test_road_valley_ridge_cliff():
    cells = [dict(col=c, row=r, elevation_m=40 * c) for c in range(10) for r in range(10)]
    road = dict(id="rd", kind="road", points=[(50, 500), (950, 500)], width_m=10, max_grade=0.08, shoulder_m=15)
    d = Engine(proj(lines=[road], cells=cells, noise=0.0), step=5)._design(0)
    assert np.abs(np.diff(d["z"]) / np.diff(d["s"])).max() <= 0.08 + 1e-4
    _, _, z0 = run(proj(noise=0.0))
    v = dict(id="v", kind="valley", points=[(100, 500), (900, 500)], width_m=200, depth_m=30)
    rg = dict(id="g", kind="ridge", points=[(100, 500), (900, 500)], width_m=200, depth_m=80)
    _, _, zv = run(proj(lines=[v], noise=0.0)); _, _, zr = run(proj(lines=[rg], noise=0.0))
    assert zv.min() < z0.min() - 20 and zr.max() > z0.max() + 60
    cl = dict(id="c", kind="cliff", points=[(100, 500), (900, 500)], width_m=20, depth_m=60, shoulder_m=300)   # اتجاه الرسم شرقاً: اليسار = الشمال
    xs, ys, zc = run(proj(lines=[cl], noise=0.0), 201)
    north = zc[np.argmin(np.abs(ys - 530)), 100]; south = zc[np.argmin(np.abs(ys - 470)), 100]
    assert north - south > 55


def test_biomes_blend_and_limits():
    desert = dict(id="d", name="صحراء", polygon=[(0, 0), (500, 0), (500, 1000), (0, 1000)], base_elevation_m=100, noise_amplitude_m=0,
                  blend_m=100, max_elev_m=200)
    mount = dict(id="m", name="جبال", polygon=[(500, 0), (1000, 0), (1000, 1000), (500, 1000)], base_elevation_m=800, noise_amplitude_m=0, blend_m=100)
    p = proj(biomes=[desert, mount], noise=0.0)
    xs, ys, Z = run(p, 201)
    row = Z[100]
    assert abs(row[10] - 100) < 0.5 and abs(row[190] - 800) < 0.5                 # داخل كل منطقة
    assert np.all(np.diff(row) >= -1e-3)                                           # انتقال رتيب بلا قفزات
    e, _ = validate(p, engine_for(p, 513)); assert not e
    bad = proj([pf(id="k", x_m=250, y_m=500, diameter_m=300, high_m=600, low_m=100)], biomes=[desert, mount], noise=0.0)
    e, _ = validate(bad, engine_for(bad, 513)); assert any("أعلى من حدها الأقصى" in m for m in e)
    desert["clamp"] = True
    ok = proj([pf(id="k", x_m=250, y_m=500, diameter_m=300, high_m=600, low_m=100)], biomes=[desert, mount], noise=0.0)
    e, _ = validate(ok, engine_for(ok, 513)); assert not e
    _, _, Zc = run(ok, 201)
    assert Zc[:, :90].max() <= 200.01                                              # القصّ يطبَّق


def test_biome_points_match_grid():
    desert = dict(id="d", name="x", polygon=[(0, 0), (600, 0), (600, 1000), (0, 1000)], base_elevation_m=100, noise_amplitude_m=20, blend_m=200)
    p = proj(biomes=[desert])
    xs, ys, Z = run(p)
    X, Y = np.meshgrid(xs[::6], ys[::6])
    assert np.allclose(Engine(p).points(X.ravel(), Y.ravel()), Z[::6, ::6].ravel(), atol=1e-2)


def test_tiles_seamless_and_global_range():
    p = proj([pf(x_m=500, y_m=500, diameter_m=600)], export=dict(tile_px=513))
    p.world.chunk_size_m = 500
    nx, ny, mpp = tile_plan(p)
    assert (nx, ny) == (2, 2) and abs(mpp - 500 / 512) < 1e-9
    with tempfile.TemporaryDirectory() as t:
        out = os.path.join(t, "o.zip")
        export_tiles(p, out)
        z = zipfile.ZipFile(out)
        idx = json.loads(z.read("tiles_index.json"))
        im = lambda c, r: cv2.imdecode(np.frombuffer(z.read(f"tiles/tile_{c}_{r}.png"), np.uint8), cv2.IMREAD_UNCHANGED).astype(int)
        a, b, c = im(0, 0), im(1, 0), im(0, 1)
        assert a.shape == (513, 513) and np.abs(a[:, -1] - b[:, 0]).max() <= 1          # حافة شرقية = غربية
        assert np.abs(a[-1, :] - c[0, :]).max() <= 1                                      # حافة جنوبية = شمالية
        full = max(int(im(i, j).max()) for i in range(2) for j in range(2))
        assert full == 65535 and idx["z_max_m"] > idx["z_min_m"]


def test_png16_roundtrip_rect_world():
    p = proj([pf()], size=(1000, 500))
    xs, ys, Z = run(p, 257)
    z = zipfile.ZipFile(io.BytesIO(build_zip(p, Z)))
    img = cv2.imdecode(np.frombuffer(z.read("heightmap_16bit.png"), np.uint8), cv2.IMREAD_UNCHANGED)
    meta = json.loads(z.read("metadata.json"))
    assert img.dtype == np.uint16 and img.shape == Z.shape == (meta["height_px"], meta["width_px"])
    back = meta["z_min_m"] + img.astype(np.float64) / 65535 * meta["height_range_m"]
    assert np.abs(back - Z).max() <= 0.5 * meta["height_range_m"] / 65535 + 1e-3


# ───────────── v4: ضبط النهر، التعرية، المواقع، التفاصيل، build.json ─────────────
from app.schemas import Site, Zone


def test_river_regrade_makes_valley_instead_of_trench():
    hill = pf(id="h", kind="hill", x_m=500, y_m=500, diameter_m=500, high_m=130, low_m=50, roughness=0)
    rv = lambda mode: dict(id="r", kind="river", points=[(50, 500), (500, 500), (950, 500)], width_m=20, depth_m=4, grade_mode=mode)
    res = {}
    for mode in ("carve", "regrade"):
        xs, ys, Z = run(proj([hill], [rv(mode)], noise=0.0), 401)
        i = np.argmin(np.abs(xs - 500))
        res[mode] = [float(Z[np.argmin(np.abs(ys - (500 + d))), i]) for d in (0, 15, 30, 60)]
    c, g = res["carve"], res["regrade"]
    assert c[3] - c[0] > 60                                   # الحفر القديم: جدار عمودي تقريباً
    assert g[0] < g[1] < g[2] < g[3] and g[3] - g[0] < 15      # التسوية: النهر أخفض نقطة وضفاف تدريجية
    e = Engine(proj([hill], [rv("regrade")], noise=0.0), step=5)
    assert np.all(np.diff(e._design(1)["bed"]) <= 1e-6)


def test_erosion_deterministic_lowers_peak_and_tiles_agree():
    mt = pf(id="m", kind="mountain", diameter_m=800, high_m=400, low_m=50, shape="rugged", roughness=0.8)
    er = dict(enabled=True, resolution=257, iterations=20, max_depth_m=15)
    xs, ys, Za = run(proj([mt], noise=10.0), 129)
    pe = proj([mt], noise=10.0, erosion=er)
    Zb = Engine(pe, step=5).grid(xs, ys)
    Zc = Engine(pe, step=5).grid(xs, ys)
    assert np.array_equal(Zb, Zc) and Zb.max() < Za.max() and np.isfinite(Zb).all()
    left = Engine(pe, step=5).grid(xs[:65], ys)                       # نافذة جزئية = نفس القيم (لا شقوق)
    assert np.allclose(Zb[:, :65], left, atol=1e-4)
    X, Y = np.meshgrid(xs[::9], ys[::9])
    assert np.allclose(Engine(pe, step=5).points(X.ravel(), Y.ravel()), Zb[::9, ::9].ravel(), atol=1e-2)


def test_site_pad_is_flat_and_blends_out():
    hill = pf(id="h", kind="hill", x_m=500, y_m=500, diameter_m=700, high_m=100, low_m=50)
    s = Site(id="v", kind="village", x_m=500, y_m=500, diameter_m=300, blend_m=60)
    p = proj([hill], sites=[s], noise=5.0)
    xs, ys, Z = run(p, 401)
    yy, xx = np.meshgrid(ys, xs, indexing="ij")
    r = np.hypot(xx - 500, yy - 500)
    assert Z[r <= 150].std() < 1e-4                                   # مستوية تماماً داخل البصمة
    assert np.all(np.abs(np.diff(Z[200, 220:320])) < 2.0)             # انتقال ناعم خارجها
    rect = Site(id="f", kind="industrial", x_m=200, y_m=200, shape="rect", width_m=200, length_m=100, rotation_deg=30, blend_m=30)
    xs, ys, Z = run(proj([], sites=[rect], noise=20.0), 401)
    th = math.radians(30); u = (xx - 200) * math.cos(th) + (yy - 200) * math.sin(th); v = -(xx - 200) * math.sin(th) + (yy - 200) * math.cos(th)
    assert Z[(np.abs(u) < 95) & (np.abs(v) < 45)].std() < 1e-4


def test_site_rules():
    a = Site(id="a", x_m=300, y_m=300, diameter_m=300); b = Site(id="b", x_m=500, y_m=300, diameter_m=300)
    p = proj(sites=[a, b]); e, _ = validate(p, engine_for(p, 513)); assert any("تداخل موقعين" in m for m in e)
    lake = pf(id="l", kind="lake", x_m=700, y_m=700, diameter_m=300, high_m=50, low_m=20)
    p = proj([lake], sites=[Site(id="c", x_m=700, y_m=700, diameter_m=100)]); e, _ = validate(p, engine_for(p, 513)); assert any("داخل بحيرة" in m for m in e)
    steep = pf(id="m", kind="mountain", diameter_m=800, high_m=700, low_m=50, roughness=0)
    p = proj([steep], sites=[Site(id="d", x_m=360, y_m=500, diameter_m=100)], noise=0.0)
    _, w = validate(p, engine_for(p, 513)); assert any("التسوية كبيرة" in m for m in w)


def test_relief_zone_only_inside_polygon():
    z = Zone(id="z", layer="hummocks", polygon=[(200, 200), (800, 200), (800, 800), (200, 800)], density=1, falloff_m=50, amplitude_m=2, wavelength_m=20)
    xs, ys, Z = run(proj(zones=[z], noise=0.0), 201)
    assert Z[60:140, 60:140].std() > 0.3 and np.all(Z[:30, :30] == Z[0, 0])


def test_build_json_masks_and_blender_script_in_export():
    road = dict(id="rd", kind="road", points=[(50, 500), (950, 500)], width_m=10, shoulder_m=10)
    rv = dict(id="r", kind="river", points=[(50, 900), (950, 850)], width_m=20, depth_m=4, falls=[dict(at=0.5, height_m=5, length_m=10)])
    grass = Zone(id="g", layer="grass", polygon=[(100, 100), (900, 100), (900, 900), (100, 900)], density=1, falloff_m=20, patchiness=0, max_slope_deg=45)
    site = Site(id="v", kind="village", name="قرية", x_m=300, y_m=300, diameter_m=150)
    p = proj([pf(id="l", kind="lake", x_m=700, y_m=300, diameter_m=200, high_m=50, low_m=20), pf(id="c", kind="cave", x_m=800, y_m=800, diameter_m=60, high_m=50, low_m=40)],
             [road, rv], sites=[site], zones=[grass], noise=3.0, export=dict(mask_px=513))
    xs, ys, Z = run(p, 129)
    zf = zipfile.ZipFile(io.BytesIO(build_zip(p, Z)))
    names = zf.namelist()
    assert "build.json" in names and "masks/grass.png" in names and "import_build.py" in names
    B = json.loads(zf.read("build.json"))
    assert B["format"] == "terrainforge-build" and B["heightmap"]["mode"] == "single" and B["heightmap"]["file_png"] in names
    assert B["sites"][0]["level_z"] > 0 and len(B["sites"][0]["outline"]) == 48 and B["water"]["lakes"][0]["water_level_m"] == 50
    kinds = {l["kind"] for l in B["features"]["lines"]}; assert kinds == {"road", "river"}
    rvl = [l for l in B["features"]["lines"] if l["kind"] == "river"][0]
    assert len(rvl["water_z"]) == len(rvl["polyline"]) and all(a >= b for a, b in zip(rvl["bed_z"], rvl["bed_z"][1:]))
    assert len(B["water"]["waterfalls"]) == 1 and B["markers"][0]["id"] == "c"
    m = cv2.imdecode(np.frombuffer(zf.read("masks/grass.png"), np.uint8), cv2.IMREAD_UNCHANGED)
    assert m.dtype == np.uint8 and m.shape == (513, 513)
    ys_m = np.linspace(1000, 0, 513); xs_m = np.linspace(0, 1000, 513)
    assert m[np.argmin(np.abs(ys_m - 700)), np.argmin(np.abs(xs_m - 600))] > 200        # عشب في الوسط
    assert m[np.argmin(np.abs(ys_m - 500)), np.argmin(np.abs(xs_m - 500))] == 0         # لا عشب على الطريق
    assert m[np.argmin(np.abs(ys_m - 300)), np.argmin(np.abs(xs_m - 300))] == 0         # ولا فوق القرية
    assert m[np.argmin(np.abs(ys_m - 300)), np.argmin(np.abs(xs_m - 700))] == 0         # ولا داخل البحيرة
    assert m[10, 10] == 0                                                              # خارج المضلع


def test_materials_three_point_gradient_rules_and_splats():
    mt = pf(kind="mountain", diameter_m=800, high_m=400, low_m=50, shape="cone", roughness=0, mat_low="grass", mat_mid="rock", mat_high="snow")
    rv = dict(id="r", kind="river", points=[(50, 900), (950, 900)], width_m=30, depth_m=3, mat_main="mud", mat_edge="sand")
    p = proj([mt], [rv], noise=0.0, paint=dict(slope_material=None, beach_material=None), export=dict(mask_px=513))
    xs, ys, Z = run(p, 201)
    pt, _ = paint_fn(p, Engine(p, step=5), Z, xs, ys)
    assert np.allclose(sum(pt.W.values()), 1.0, atol=1e-4)                       # المجموع = 1 دائماً
    iy, ix = lambda y: int(np.argmin(np.abs(ys - y))), lambda x: int(np.argmin(np.abs(xs - x)))
    assert pt.W["snow"][iy(500), ix(500)] > 0.9                                   # القمة ثلج
    assert pt.W["rock"][iy(500), ix(700)] > 0.6                                   # منتصف الارتفاع صخر
    assert pt.W["grass"][iy(500), ix(870)] > 0.6                                  # السفح عشب
    assert pt.W["mud"][iy(900), ix(500)] > 0.9 and pt.W["sand"][iy(922), ix(500)] > 0.5   # مجرى طين وضفاف رمل
    imgs, info = pack_splats(p, pt)
    assert len(info) == 5 and len(imgs) == 2 and imgs[0].shape[2] == 4
    assert {i["channel"] for i in info if i["splat"].endswith("_0.png")} == set("RGBA")
    assert colors_rgb(p, pt).shape == Z.shape + (3,)
    # الميل الشديد يتحول صخراً تلقائياً
    p2 = proj([pf(kind="mountain", diameter_m=800, high_m=700, low_m=50, shape="cone", roughness=0)], noise=0.0)
    xs, ys, Z2 = run(p2, 201); pt2, sl = paint_fn(p2, Engine(p2, step=5), Z2, xs, ys)
    assert pt2.W["rock"][iy(500), ix(700)] > 0.9 and sl.max() > 48


def test_export_has_splats_and_materials_in_build_json():
    mt = pf(kind="mountain", diameter_m=600, high_m=300, low_m=50, mat_low="grass", mat_mid="dirt", mat_high="rock")
    p = proj([mt], noise=3.0, materials=[dict(id="dirt", name="تراب", color="#aa8855", albedo="textures/dirt_albedo.jpg", normal="textures/dirt_normal.jpg", tile_m=4)],
             export=dict(mask_px=513))
    xs, ys, Z = run(p, 65)
    zf = zipfile.ZipFile(io.BytesIO(build_zip(p, Z)))
    B = json.loads(zf.read("build.json"))
    assert "masks/splat_0.png" in zf.namelist() and "masks/materials_preview.png" in zf.namelist()
    d = [m for m in B["materials"] if m["id"] == "dirt"][0]
    assert d["albedo"] == "textures/dirt_albedo.jpg" and d["tile_m"] == 4 and d["splat"] == "masks/splat_0.png" and d["channel"] in "RGBA"
    assert B["features"]["points"][0]["materials"] == {"low": "grass", "mid": "dirt", "high": "rock"} and B["paint_rules"]["default_material"] == "grass"


# ───────────── v6: توجيه ذكي، اقتراح مواقع/مباني ─────────────
def test_smart_road_avoids_mountain_and_respects_grade():
    mt = pf(id="m", kind="mountain", x_m=500, y_m=500, diameter_m=500, high_m=300, low_m=50, shape="cone", roughness=0)
    p = proj([mt], noise=0.0)
    r = route(p, "road", [(50, 500), (950, 500)], resolution=257, max_grade=0.08)
    pts = np.asarray(r["points"])
    assert np.hypot(pts[:, 0] - 500, pts[:, 1] - 500).min() > 200                       # لم يمرّ فوق القمة
    straight = np.hypot(900, 0)
    assert r["length_m"] > straight and r["max_grade"] < 0.5 and pts[0].tolist() == [50.0, 500.0] and pts[-1].tolist() == [950.0, 500.0]


def test_smart_road_avoids_lake_and_fails_when_blocked():
    lake = pf(id="l", kind="lake", x_m=500, y_m=500, diameter_m=400, high_m=50, low_m=20)
    p = proj([lake], noise=0.0)
    r = route(p, "road", [(50, 500), (950, 500)], resolution=257)
    pts = np.asarray(r["points"]); assert np.hypot(pts[:, 0] - 500, pts[:, 1] - 500).min() >= 195
    p2 = proj([pf(id="l", kind="lake", x_m=500, y_m=500, diameter_m=2000, high_m=50, low_m=20)], noise=0.0)
    try:
        route(p2, "road", [(50, 500), (950, 500)], resolution=257); assert False
    except ValueError:
        pass


def test_smart_river_flows_downhill_to_sea():
    cells = [dict(col=c, row=r, elevation_m=120 - 12 * c) for c in range(10) for r in range(10)]      # ينحدر شرقاً إلى 12م
    p = proj(cells=cells, noise=0.0, export={}); p.world.sea_level_m = 14.0
    r = route(p, "river", [(60, 600)], resolution=257)
    pts = np.asarray(r["points"])
    assert pts[-1][0] > 800 and r["climb_m"] < 3 and "البحر" in r["notes"][0]
    rr = route(p, "river", [(60, 600), (900, 300)], resolution=257)                      # بمصب محدد
    assert rr["points"][-1] == [900.0, 300.0]


def test_site_suggestion_prefers_flat_land_and_reports_volumes():
    hill = pf(id="h", kind="hill", x_m=300, y_m=500, diameter_m=500, high_m=200, low_m=50, roughness=0)
    p = proj([hill], noise=0.0)
    c = suggest_sites(p, "village", 200, count=3, resolution=257)
    assert len(c) == 3 and c[0]["rms_m"] < 1.0 and c[0]["cut_m3"] + c[0]["fill_m3"] < 20000
    assert all(np.hypot(a["x_m"] - b["x_m"], a["y_m"] - b["y_m"]) >= 200 for i, a in enumerate(c) for b in c[i + 1:])
    assert all(np.hypot(a["x_m"] - 300, a["y_m"] - 500) > 100 for a in c[:1]) or c[0]["rms_m"] < 1


def test_lots_inside_pad_with_spacing_and_determinism():
    s = Site(id="v", kind="village", x_m=500, y_m=500, diameter_m=300, density=0.8, seed=4)
    a, b = lots_for_site(s, 40.0), lots_for_site(s, 40.0)
    assert a == b and len(a) > 5
    for l in a:
        assert math.hypot(l["x_m"] - 500, l["y_m"] - 500) <= 150 - 5
    assert min(math.hypot(x["x_m"] - y["x_m"], x["y_m"] - y["y_m"]) for i, x in enumerate(a) for y in a[i + 1:]) >= 20 / math.sqrt(0.8) - 1e-6


def _poi(**kw):
    d = dict(id="p", kind="poi", x_m=500, y_m=500)
    d.update(kw)
    return Poi(**d)


def test_simulation_time_distance_and_unreachable():
    pois = [_poi(id="s", kind="player_start", x_m=100, y_m=100), _poi(id="a", kind="story", x_m=900, y_m=100, order=1, dwell_min=3, radius_m=60),
            _poi(id="b", kind="boss", x_m=900, y_m=900, order=2, dwell_min=5, difficulty=8)]
    p = proj(noise=0.0); p.pois = pois; p.player.speed_mps = 5.0
    r = simulate(p, 257)
    assert not r["warnings"] and len(r["legs"]) == 2 and all(l["reachable"] for l in r["legs"])
    t = r["totals"]
    assert 1500 < t["distance_m"] < 1800                                            # 800 + 800 تقريباً مع انحناء الشبكة
    assert abs(t["walk_s"] - t["distance_m"] / 5.0) / (t["distance_m"] / 5.0) < 0.12   # أرض مستوية: زمن ≈ مسافة / سرعة
    assert abs(t["dwell_s"] - (3 + 5) * 60) < 1e-6 and abs(t["total_s"] - t["walk_s"] - t["dwell_s"]) < 1e-6
    assert [m["id"] for m in r["stops"]] == ["s", "a", "b"] and len(r["profile"]["distance_m"]) > 10
    ring = proj([pf(id="L", kind="lake", x_m=900, y_m=900, diameter_m=500, high_m=50, low_m=10)], noise=0.0)
    ring.pois = pois; r2 = simulate(ring, 257)
    assert any("لا يمكن للاعب الوصول" in w for w in r2["warnings"])                # الهدف داخل بحيرة
    try:
        p3 = proj(noise=0.0); p3.pois = [_poi(id="a", x_m=5, y_m=5, order=1)]; simulate(p3, 257); assert False
    except ValueError as e:
        assert "نقطة انطلاق" in str(e)


def test_simulation_detours_around_steep_mountain_and_slows_uphill():
    mt = pf(id="m", kind="mountain", x_m=500, y_m=500, diameter_m=600, high_m=700, low_m=50, shape="cone", roughness=0)
    pois = [_poi(id="s", kind="player_start", x_m=50, y_m=500), _poi(id="a", kind="story", x_m=950, y_m=500, order=1)]
    p = proj([mt], noise=0.0); p.pois = pois
    r = simulate(p, 257)
    assert r["legs"][0]["reachable"] and r["legs"][0]["distance_m"] > 1000 and r["totals"]["max_slope_deg"] <= 40.5


def test_visibility_blocked_by_hill_and_landmark_height_helps():
    Zs = np.zeros((101, 101)); Zs[:, 45:55] = 100.0                                    # جدار عالٍ بين المراقب والهدف
    assert not __import__("app.gameplay", fromlist=["los"]).los(Zs, 1000, 1000, 100, 500, 1.7, 900, 500, 2.0)
    assert not __import__("app.gameplay", fromlist=["los"]).los(Zs, 1000, 1000, 100, 500, 1.7, 900, 500, 50.0)
    assert __import__("app.gameplay", fromlist=["los"]).los(Zs, 1000, 1000, 100, 500, 1.7, 900, 500, 500.0)   # برج شاهق يُرى
    X, Y, vis, d = rays(Zs, 1000, 1000, 100, 500, 1.7, 800, 90)
    east = vis[0]                                                                       # الشعاع شرقاً: يُحجب بعد الجدار فقط
    assert east[d < 330].all() and not east[d > 470].any()                              # خلف الجدار غير مرئي
    p = proj(noise=0.0); p.pois = [_poi(id="s", kind="player_start", x_m=100, y_m=100), _poi(id="L", kind="landmark", x_m=900, y_m=100, order=1, landmark_height_m=30)]
    r = simulate(p, 257)
    seen = [x for x in r["view"]["pois_seen"] if x["id"] == "L"][0]
    assert seen["ever_seen"] and seen["first_seen_at_m"] == 0.0 and r["view"]["bands_m"][0] > 0
    vs = viewshed(p, 500, 500, 1.7, 400, 257)
    assert vs["mask"].dtype == np.uint8 and 0.5 < vs["visible_fraction_of_disc"] <= 1.0   # أرض مستوية: ترى القرص كله تقريباً


def test_poi_arena_flatten_and_validation_warnings():
    hill = pf(id="h", kind="hill", x_m=500, y_m=500, diameter_m=700, high_m=120, low_m=50, roughness=0)
    boss = _poi(id="b", kind="boss", x_m=500, y_m=500, radius_m=100, flatten=True, blend_m=40)
    p = proj([hill], noise=0.0); p.pois = [boss, _poi(id="s", kind="player_start", x_m=100, y_m=100)]
    xs, ys, Z = run(p, 401)
    yy, xx = np.meshgrid(ys, xs, indexing="ij")
    assert Z[np.hypot(xx - 500, yy - 500) <= 100].std() < 1e-4                          # حلبة الزعيم مستوية
    _, w = validate(p, engine_for(p, 513)); assert not any("غير مستوية" in m for m in w)
    boss2 = _poi(id="b", kind="boss", x_m=500, y_m=500, radius_m=100, flatten=False)
    p2 = proj([hill], noise=0.0); p2.pois = [boss2]
    _, w = validate(p2, engine_for(p2, 513))
    assert any("غير مستوية" in m for m in w) and any("نقطة انطلاق" in m for m in w)


def test_build_json_has_chunks_lod_lots_and_gameplay():
    site = Site(id="v", kind="village", name="قرية", x_m=300, y_m=300, diameter_m=200, density=0.8)
    p = proj([pf(id="m", kind="mountain", x_m=800, y_m=800, diameter_m=300, high_m=200, low_m=50)], sites=[site], noise=2.0, export=dict(mask_px=513))
    p.pois = [_poi(id="s", kind="player_start", x_m=100, y_m=100), _poi(id="B", kind="boss", name="زعيم", x_m=500, y_m=250, radius_m=60, order=1, difficulty=7)]
    xs, ys, Z = run(p, 65)
    B = json.loads(zipfile.ZipFile(io.BytesIO(build_zip(p, Z))).read("build.json"))
    ch = B["chunks"]
    assert ch["chunks_x"] == 2 and ch["chunks_y"] == 2 and len(ch["chunks"]) == 4 and len(ch["lod"]["levels"]) == 4 and len(ch["hlod"]) == 1
    by = {c["id"]: c for c in ch["chunks"]}
    assert "v" in by["0_1"]["features"]["sites"] and "m" in by["1_0"]["features"]["points"] and "B" in by["0_1"]["features"]["pois"] + by["1_1"]["features"]["pois"] + by["0_0"]["features"]["pois"] + by["1_0"]["features"]["pois"]
    g = B["gameplay"]
    assert g["player_start"]["id"] == "s" and g["expected_route"]["totals"]["total_s"] > 0 and g["expected_route"]["legs"][0]["points"][0][2] is not None
    assert len(B["sites"][0]["building_lots"]) > 3 and g["pois"][1]["difficulty"] == 7


def test_tiles_have_hlod_levels():
    p = proj([pf(x_m=500, y_m=500, diameter_m=600)], export=dict(tile_px=513))
    p.world.chunk_size_m = 500
    with tempfile.TemporaryDirectory() as t:
        out = os.path.join(t, "o.zip"); export_tiles(p, out)
        z = zipfile.ZipFile(out); idx = json.loads(z.read("tiles_index.json"))
        assert idx["hlod"][0]["level"] == 1 and idx["hlod"][0]["group_chunks"] == 2 and "hlod/level1/tile_0_0.png" in z.namelist()
        h = cv2.imdecode(np.frombuffer(z.read("hlod/level1/tile_0_0.png"), np.uint8), cv2.IMREAD_UNCHANGED)
        assert h.shape == (513, 513) and h.dtype == np.uint16
        B = json.loads(z.read("build.json")); assert B["heightmap"]["hlod"][0]["level"] == 1 and B["chunks"]["chunk_px"] == 513


def test_all_blender_names_are_english_and_unique():
    import re
    site = Site(id="قرية-1", kind="village", name="قرية الشمال", x_m=300, y_m=300, diameter_m=200)
    rv = dict(id="نهر-1", kind="river", points=[(50, 900), (950, 850)], width_m=20, depth_m=4, falls=[dict(at=.5, height_m=5, length_m=10)])
    rd = dict(id="طريق-1", kind="road", points=[(50, 500), (950, 500)], width_m=10)
    p = proj([pf(id="جبل-1", kind="mountain", x_m=800, y_m=800, diameter_m=300, high_m=200, low_m=50),
              pf(id="كهف-1", kind="cave", x_m=700, y_m=300, diameter_m=60, high_m=50, low_m=40)], [rv, rd], sites=[site], noise=2.0,
             materials=[dict(id="مادة-1", name="طين أحمر", color="#aa5533")], export=dict(mask_px=513))
    p.name = "عالم تجريبي"
    p.zones = [Zone(id="نباتات-1", name="عشب", layer="grass", polygon=[(100, 100), (900, 100), (900, 400), (100, 400)])]
    p.pois = [_poi(id="s", kind="player_start", name="البداية", x_m=100, y_m=100), _poi(id="b", kind="boss", name="Dragon زعيم", x_m=500, y_m=250, radius_m=60, order=1)]
    xs, ys, Z = run(p, 65)
    B = json.loads(zipfile.ZipFile(io.BytesIO(build_zip(p, Z))).read("build.json"))
    secs = [B["features"]["points"], B["features"]["lines"], B["sites"], B["gameplay"]["pois"], B["scatter_zones"], B["water"]["waterfalls"],
            B["markers"], B["gameplay"]["expected_route"]["legs"], B["materials"]]
    names = [x["blender_name"] for sec in secs for x in sec]
    assert len(names) >= 12 and all(re.fullmatch(r"[A-Za-z0-9_\-]+", n) for n in names)
    uniq = [x["blender_name"] for sec in secs if sec is not B["markers"] for x in sec]            # العلامة تشير إلى نفس معلم الكهف
    assert len(set(uniq)) == len(uniq)
    assert B["project_slug"] == "World" and B["features"]["points"][0]["label"] == "Mountain"
    assert "poi_boss_01_Dragon" in names and "site_village_01" in names


# ───────────── v7: عالم بمنسوب واحد، مناسيب مطلقة، ضوضاء بنطاق منسجمة مع المعالم ─────────────
def test_flat_world_is_exactly_one_elevation_even_with_amplitude_set():
    p = proj(noise=30.0, noise_mode="off", elevation_m=200)
    _, _, Z = run(p, 101)
    assert Z.min() == Z.max() == 200.0


def test_absolute_valley_floor_and_ridge_top_on_flat_world():
    v = dict(id="v", kind="valley", points=[(100, 500), (900, 500)], width_m=200, depth_m=1, floor_m=50, profile="u")
    rg = dict(id="g", kind="ridge", points=[(100, 800), (900, 800)], width_m=200, depth_m=1, top_m=320, profile="u", roughness=0)
    xs, ys, Z = run(proj(lines=[v, rg], noise=0.0, noise_mode="off", elevation_m=200), 201)
    i = np.argmin(np.abs(xs - 500))
    assert abs(Z[np.argmin(np.abs(ys - 500)), i] - 50) < 0.5                     # 200 -> 50: هبوط 150 م
    assert abs(Z[np.argmin(np.abs(ys - 800)), i] - 320) < 0.5                    # قمة مطلقة 320
    col = Z[:, i]; side = [col[np.argmin(np.abs(ys - (500 + d)))] for d in (0, 30, 60, 100)]
    assert side[0] < side[1] < side[2] < side[3] <= 200.0 + 1e-3                 # ضفاف تدريجية نحو منسوب العالم


def test_range_noise_stays_in_range_and_follows_features():
    mt = pf(id="m", kind="mountain", x_m=250, y_m=500, diameter_m=300, high_m=600, low_m=200, roughness=0)
    bs = pf(id="b", kind="basin", x_m=750, y_m=500, diameter_m=300, high_m=200, low_m=60, roughness=0)
    p = proj([mt, bs], noise=0.0, noise_mode="range", noise_min_m=200, noise_max_m=250, noise_bias=0.8, elevation_m=200, noise_scale_m=300)
    p_free = proj(noise=0.0, noise_mode="range", noise_min_m=200, noise_max_m=250, noise_bias=0.8, elevation_m=200, noise_scale_m=300)
    xs, ys, Zf = run(p_free, 201)
    assert Zf.min() >= 200 - 1e-3 and Zf.max() <= 250 + 1e-3 and Zf.max() - Zf.min() > 35        # يستعمل النطاق كاملاً بلا معالم
    _, _, Z = run(p, 201)
    yy, xx = np.meshgrid(ys, xs, indexing="ij")
    ring = lambda cx: (np.hypot(xx - cx, yy - 500) > 190) & (np.hypot(xx - cx, yy - 500) < 300)
    assert Z[ring(250)].mean() > Z[ring(750)].mean() + 5                                         # حول الجبل أعلى منه حول المنخفض
    assert Z[ring(250)].mean() > Zf[ring(250)].mean() + 3 and Z[ring(750)].mean() < Zf[ring(750)].mean() - 3   # مقارنة بالضوضاء الحرة


def test_range_mode_points_grid_and_window_consistency():
    mt = pf(id="m", kind="mountain", x_m=300, y_m=500, diameter_m=300, high_m=500, low_m=200)
    v = dict(id="v", kind="valley", points=[(100, 200), (900, 300)], width_m=100, depth_m=1, floor_m=80)
    p = proj([mt], [v], noise=0.0, noise_mode="range", noise_min_m=200, noise_max_m=250, elevation_m=200, noise_scale_m=300)
    xs, ys, Z = run(p, 101)
    assert np.array_equal(Z[:, :51], Engine(p, step=5).grid(xs[:51], ys))
    X, Y = np.meshgrid(xs[::7], ys[::7])
    assert np.allclose(Engine(p, step=5).points(X.ravel(), Y.ravel()), Z[::7, ::7].ravel(), atol=1e-2)


def test_atmosphere_defaults_roundtrip_and_build_json():
    import pytest
    from app.schemas import Atmosphere
    old = proj([], []).model_dump(); old.pop("atmosphere")                      # ملف v7 قديم بلا جو
    assert Project.model_validate(old).atmosphere == Atmosphere()
    p = proj([], [], export=dict(mask_px=513))
    p.atmosphere = Atmosphere(sun_elevation=15, engine="CYCLES", fog=False, camera_height_above_peak_m=300)
    xs, ys, Z = run(p, 129)
    B = json.loads(zipfile.ZipFile(io.BytesIO(build_zip(p, Z))).read("build.json"))
    a = B["atmosphere"]
    assert a["sun_elevation"] == 15 and a["engine"] == "CYCLES" and a["fog"] is False and a["fog_density"] is None and a["camera_height_above_peak_m"] == 300
    for bad in (dict(sun_elevation=95), dict(engine="X"), dict(fog_density=0), dict(f_stop=0)):
        with pytest.raises(Exception):
            Atmosphere(**bad)


def test_pbr_surface_and_material_fields_reach_build_json():
    import pytest
    from app.schemas import Surface, Material
    old = proj([], []).model_dump(); old.pop("surface")                         # ملف قديم بلا surface
    assert Project.model_validate(old).surface == Surface()
    p = proj([], [], export=dict(mask_px=513))
    p.surface = Surface(triplanar=False, relief_m=0.4, normal_convention="DX")
    p.materials = [Material(id="rock", color="#777777", pack="textures/rock_01", roughness_value=0.7, height="h.png")]
    xs, ys, Z = run(p, 129)
    B = json.loads(zipfile.ZipFile(io.BytesIO(build_zip(p, Z))).read("build.json"))
    assert B["surface"]["triplanar"] is False and B["surface"]["relief_m"] == 0.4 and B["surface"]["normal_convention"] == "DX"
    rock = [m for m in B["materials"] if m["id"] == "rock"]
    if rock:                                                                     # تظهر المادة فقط إن استُعملت في التلوين
        assert rock[0]["pack"] == "textures/rock_01" and rock[0]["roughness_value"] == 0.7 and rock[0]["height"] == "h.png"
    for bad in (dict(relief_m=-1), dict(normal_convention="X"), dict(triplanar_blend=2), dict(break_scale_m=0)):
        with pytest.raises(Exception):
            Surface(**bad)


def test_derived_layers_masks_and_paint_rules():
    from app.schemas import Derived
    from app.derived import derive, slope_classes
    p = proj([], [], export=dict(mask_px=513))
    p.derived = Derived(convex_material="rock", wet_material="mud")
    xs, ys, Z = run(p, 129)
    dx, dy = xs[1] - xs[0], ys[0] - ys[1]
    dv = derive(Z, dx, dy, p.derived)
    for k in ("curv_convex", "curv_concave", "cavity", "flow", "stream", "wetness"):
        assert dv[k].shape == Z.shape and 0.0 <= dv[k].min() and dv[k].max() <= 1.0
    assert set(np.unique(slope_classes(np.array([1., 8., 20., 40.]), [5, 15, 30]))) == {0, 1, 2, 3}
    names = zipfile.ZipFile(io.BytesIO(build_zip(p, Z))).namelist()
    assert "masks/derived_cavity.png" in names and "masks/derived_slope_class.png" in names
    with pytest.raises(Exception):
        Derived(slope_classes_deg=[0, 95])


def test_scatter_positions_respect_distance_density_and_determinism():
    from scipy.spatial import cKDTree
    from app.schemas import ScatterSpecies
    from app.scatter import place
    N = 129; L = 1000.0
    xs = np.linspace(0, L, N); ys = np.linspace(L, 0, N); X, Y = np.meshgrid(xs, ys)
    Z = 50 + 0.02 * X
    dens = np.clip(1 - np.hypot(X - 500, Y - 500) / 300, 0, 1)
    sp = ScatterSpecies(id="pine", min_dist_m=10, seed=4, max_count=5000)
    a, b = place(sp, dens, Z, xs, ys), place(sp, dens, Z, xs, ys)
    assert np.array_equal(a["x"], b["x"]) and len(a["x"]) > 100
    pts = np.c_[a["x"], a["y"]]
    assert cKDTree(pts).query(pts, k=2)[0][:, 1].min() >= a["min_dist_m"] - 1e-6
    assert (np.hypot(a["x"] - 500, a["y"] - 500) > 300).sum() == 0
    assert place(sp, np.zeros_like(dens), Z, xs, ys) is None
    with pytest.raises(Exception):
        ScatterSpecies(id="x", scale_min=2, scale_max=1)


def test_tile_detail_applies_keeps_edges_seamless_and_reports():
    from app.schemas import Detail, Material
    base = proj([pf(x_m=500, y_m=500, diameter_m=600)], export=dict(tile_px=513), materials=[Material(id="grass", color="#5c8a3c", detail_amp_m=1.5, detail_kind="rock")])
    base.world.chunk_size_m = 500                                                        # دقة ~0.98 م/بكسل
    def tiles(p):
        with tempfile.TemporaryDirectory() as t:
            out = os.path.join(t, "o.zip"); export_tiles(p, out); z = zipfile.ZipFile(out)
            im = lambda c, r: cv2.imdecode(np.frombuffer(z.read(f"tiles/tile_{c}_{r}.png"), np.uint8), cv2.IMREAD_UNCHANGED).astype(int)
            return json.loads(z.read("tiles_index.json")), im(0, 0), im(1, 0), im(0, 1)
    idx0, a0, _, _ = tiles(base)
    assert idx0["detail"]["applied"] is False
    on = base.model_copy(deep=True); on.detail = Detail(enabled=True, wavelength_max_m=24)
    idx1, a, b, c = tiles(on)
    assert idx1["detail"]["applied"] is True and "grass" in idx1["detail"]["materials"]
    assert np.abs(a[:, -1] - b[:, 0]).max() <= 1 and np.abs(a[-1, :] - c[0, :]).max() <= 1   # لا شقوق مع التفاصيل
    assert np.abs(a - a0).max() > 0                                                      # التفاصيل غيّرت الارتفاعات فعلاً
    coarse = base.model_copy(deep=True); coarse.detail = Detail(enabled=True, wavelength_max_m=1.5)   # أطول موجة أقصر من بكسلين: تُهمَل مع سبب
    assert tiles(coarse)[0]["detail"]["applied"] is False and "reason" in tiles(coarse)[0]["detail"]


def test_water_maps_depth_shore_foam_flow():
    import types as _t
    from app.water import build as wbuild, encode as wencode
    N = 257; L = 2000.0
    xs = np.linspace(0, L, N); ys = np.linspace(L, 0, N); X, Y = np.meshgrid(xs, ys)
    Z = 100 + 0.1 * X - 40 * np.exp(-((X - 1200) ** 2 + (Y - 1200) ** 2) / (2 * 120 ** 2))      # بحيرة محفورة
    lake = dict(x=1200.0, y=1200.0, radius_m=150.0, water_level_m=float(Z[int((L - 1200) / (L / (N - 1))), int(1200 / (L / (N - 1)))] + 15))
    cfg = _t.SimpleNamespace(shore_width_m=10.0, foam_width_m=4.0, rapids_slope_deg=6.0, foam_amount=1.0)
    M = wbuild(Z, xs, ys, 50.0, [lake], [], cfg)
    assert M["depth"].max() > 10 and M["water_mask"].any() and M["depth"][~M["water_mask"]].max() <= 0.03
    assert (M["shore"][M["water_mask"]] == 0).all() and (M["foam"][~M["water_mask"]] == 0).all() and M["shore"].max() > 0
    dmax, pd, ps, pf, pfl = wencode(M)
    im = cv2.imdecode(np.frombuffer(pd, np.uint8), cv2.IMREAD_UNCHANGED)
    assert im.dtype == np.uint16 and np.abs(im / 65535 * dmax - M["depth"]).max() < 1e-3
    river = dict(polyline=[(1900.0 - 100 * i, 300.0) for i in range(10)], water_z=[float(100 + 0.1 * (1900 - 100 * i) + 1.2) for i in range(10)], width_m=30.0)
    Z2 = np.where(np.abs(Y - 300) < 20, Z - 3.0, Z)
    R = wbuild(Z2, xs, ys, 50.0, [], [river], cfg)
    assert R["river"].any() and (R["flow"][R["river"]][:, 0].mean() < 0.5)                  # يجري نحو الغرب (x يتناقص)


def test_road_masks_area_shoulder_dust_and_export():
    from app.roads import build as rbuild
    from app.schemas import Roads
    N = 257; L = 2000.0; dx = L / (N - 1)
    xs = np.linspace(0, L, N); ys = np.linspace(L, 0, N)
    road = dict(polyline=[[float(x), 1000.0, 0.0] for x in np.linspace(100, 1900, 60)], width_profile_m=[10.0] * 60, shoulder_m=12.0)
    M = rbuild(xs, ys, [road], 3.0)
    assert abs(M["surface"].sum() * dx * dx / (1800 * 10) - 1) < 0.1                      # المساحة محفوظة ±10%
    assert abs(M["shoulder"].sum() * dx * dx / (2 * 12 * 1800) - 1) < 0.1
    assert M["dust"].max() > 0 and (M["dust"][M["surface"] > 0.99] == 0).all()
    assert rbuild(xs, ys, [], 3.0) is None
    narrow = rbuild(xs, ys, [dict(road, width_profile_m=[2.0] * 60)], 1.0)
    assert abs(narrow["surface"].sum() * dx * dx / (1800 * 2) - 1) < 0.15                 # طريق أضيق من بكسل يبقى
    old = proj([], []).model_dump(); old.pop("roads")
    assert Project.model_validate(old).roads == Roads()
    with pytest.raises(Exception):
        Roads(track_gauge_m=10)


def test_sediment_erosion_conserves_mass_fans_gullies_deterministic():
    from app.schemas import Erosion
    from app.erosion import erode
    N = 129; L = 2500.0; dx = L / (N - 1)
    xs = np.linspace(0, L, N); ys = np.linspace(L, 0, N); X, Y = np.meshgrid(xs, ys)
    Z0 = 100 + 300 * np.clip((Y - 1100) / 500, 0, 1) * (1 + np.sin(X / 220) * np.cos(Y / 260)) / 2 + 0.002 * (L - Y)
    base = dict(iterations=20, max_depth_m=10.0, thermal=False, smooth=0.0, gullies=False, fans=False)
    d = erode(Z0, dx, dx, Erosion(enabled=True, **base)) - Z0
    assert abs(d.sum()) < 1e-6 and d.min() < -0.1 and d.max() > 0.1                       # الحفر = الترسيب
    d_fans = erode(Z0, dx, dx, Erosion(enabled=True, **{**base, "fans": True, "fan_spread_m": 200.0})) - Z0
    assert abs(d_fans.sum()) < 1e-6 and (d_fans > 0.05).sum() >= (d > 0.05).sum()           # الانتشار لا يفقد كتلة ويوسّع البصمة
    g = erode(Z0, dx, dx, Erosion(enabled=True, **{**base, "gullies": True, "gully_depth_m": 3.0})) - Z0 - d
    assert g.min() >= -3.0001 and g.max() <= 1e-9 and (g < -0.05).any()
    again = erode(Z0, dx, dx, Erosion(enabled=True, **{**base, "gullies": True, "gully_depth_m": 3.0})) - Z0 - d
    assert np.array_equal(g, again)
    st = erode(Z0, dx, dx, Erosion(enabled=True, mode="stylized", iterations=20, max_depth_m=10.0))
    assert abs((st - Z0).sum()) > 10 * abs(d.sum()) + 1                                     # القديمة لا تحفظ الكتلة


def test_kit_placements_houses_walls_gate_towers_and_validation():
    from app.schemas import Kit, KitPiece
    from app.kits import plan
    pc = [KitPiece(id="h", role="house"), KitPiece(id="keep", role="main", width_m=24, length_m=24), KitPiece(id="w", role="wall", width_m=1, length_m=6),
          KitPiece(id="g", role="gate", length_m=10), KitPiece(id="t", role="tower"), KitPiece(id="v", role="house", site_kinds=["village"])]
    kit = Kit(pieces=pc, props_per_lot=0, seed=3)
    outline = [[440, 440, 50], [560, 440, 50], [560, 560, 50], [440, 560, 50], [440, 440, 50]]
    lots = [dict(x_m=500, y_m=500, width_m=38, length_m=38, rotation_deg=0, z_m=50, main=True), dict(x_m=470, y_m=470, width_m=10, length_m=8, rotation_deg=45, z_m=50, main=False)]
    site = dict(id="c1", kind="castle", center=dict(x=500, y=500, z=50), level_z=50, outline=outline, building_lots=lots)
    road = dict(polyline=[[100.0, 500.0, 0], [440.0, 500.0, 0], [500.0, 500.0, 0]])
    rows = plan(kit, [site], [road])
    roles = [r["role"] for r in rows]
    assert roles.count("main") == 1 and roles.count("house") == 1 and roles.count("gate") == 1 and roles.count("tower") == 4
    assert roles.count("wall") > 70 and all(r["piece"] != "v" for r in rows)              # قطعة القرى لا تُستعمل في قلعة
    g = [r for r in rows if r["role"] == "gate"][0]
    assert abs(g["x"] - 440) < 1 and abs(g["y"] - 500) < 1 and abs(g["yaw_deg"] - 180) < 1   # بوابة واحدة عند عبور الطريق، تواجه الخارج
    assert not [r for r in rows if r["role"] == "wall" and np.hypot(r["x"] - g["x"], r["y"] - g["y"]) < 4]
    assert rows == plan(kit, [site], [road])                                                # حتمي
    assert plan(Kit(pieces=[]), [site], [road]) == []
    with pytest.raises(Exception):
        KitPiece(id="x", site_kinds=["spaceport"])
